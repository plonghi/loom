import sympy
import numpy
import logging
import copy
import pdb
import sympy.mpmath as mpmath

from sympy import oo
from sympy.mpmath import mp
from sympy.mpmath.libmp.libhyper import NoConvergence
from warnings import warn
from pprint import pformat
from itertools import combinations

import sage_subprocess
from misc import (ctor2, r2toc, get_root_multiplicity, PSL2C,
                  delete_duplicates, gather, parse_sym_dict_str)

x, z = sympy.symbols('x z')

N_NULL_TRIPLES = 45
N_NULL_QUARTETS = 1008
NULL_TRIPLES_INDIVIDUAL = 5
NULL_QUARTETS_INDIVIDUAL = 72
SHEET_NULL_TOLERANCE = 0.001

ROOT_FINDING_MAX_STEPS = 50
ROOT_FINDING_PRECISION = 20

mp.dps = ROOT_FINDING_PRECISION

class GData:
    """
    ffr_weights:
        List of weights of the FIRST fundamental representation,
            [v_0, ... , v_k , ...],
        where 'v_k' are numpy arrays corresponding to weights.
        - For g=A_n Lie algebras, the weights are given in IR^{n+1} as
            v_0 = (1,0,...,0),
            v_1 = (0,1,0,..), 
            ...,
            v_n = (0,...,0,1). 
          In this case, it does not matter how we identify weights
          with sheets, since the Weyl group acts by permuting all of 
          them freely.
        - For g=D_n, the weights are given in IR^{n} as
            v_0 = (1,0,...,0),
            v_1 = (0,1,...,0),
            v_{n-1} = (0,...,0,1),
            v_n = (-1,0,...,0),
            v_{n+1} = (0,-1,...,0),
            v_{2n-1} = (0,...,0,-1).
          In this case, we diivde the sheets into positive and negative ones,
          and assign the weights accordingly.
          The assignment of positive sheets is almost arbitrary: from each pair
          of positive/negative sheets one can pick either, as long as one makes
          an even number of "sign mistakes". We don't keep track of this,
          as a result there is an ambiguity in distinguishing one spinor 
          representation from the other
        - For other algebras, the order is imposed by SAGE.
    """
    def __init__(self, root_system=None, representation_str=None):
        self.root_system = root_system
        # type is 'A', 'D', or 'E'.
        self.type = root_system[0]
        self.rank = eval(root_system[1:])

        representation = eval(representation_str)
        if isinstance(representation, int):
            # Representation is specified as an index
            # of a fundamental representation, i.e. n of \omega_n.
            self.fundamental_representation_index = representation
            self.highest_weight = [
                1 if i == (self.fundamental_representation_index - 1) else 0
                for i in range(self.rank)
            ]
        elif isinstance(representation, list):
            # Representation is specified in the coroot(Dynkin) basis.
            self.highest_weight = representation
            height = 0
            for i, n_i in enumerate(self.highest_weight):
                height += n_i
                if n_i == 1:
                    self.fundamental_representation_index = i + 1
            if height > 1:
                self.fundamental_representation_index = None 
                warn('{} is not a fundamental representation.'
                     .format(representation_str))
                
        sage_data = sage_subprocess.get_g_data(
            root_system, 
            self.highest_weight,
        )
        logging.info("Representation data of ({}, {}) retrieved from SAGE:\n"
                     "{}".format(root_system, representation_str,
                                 pformat(sage_data)))

        self.ffr_weights = numpy.array(sage_data['ffr_weights'])
        self.roots = numpy.array(sage_data['roots'])
        self.positive_roots = numpy.array(sage_data['positive_roots'])
        self.weights = numpy.array(sage_data['weights'])
        self.multiplicities = numpy.array(sage_data['multiplicities'])
        self.weight_basis = numpy.array(sage_data['weight_basis']),
        # The i-th row of self.coefficients is the representation
        # of self.weights[i] in the self.basis.
        self.weight_coefficients = numpy.array(
            sage_data['weight_coefficients']
        )
        self.root_color_map = self.create_root_color_map()


    def ordered_weight_pairs(self, root, ffr=False):
        """
        Return list of pairs of weight indices.
        """
        pairs = []

        if ffr is False:
            weights = self.weights
        elif ffr is True:
            weights = self.ffr_weights

        for i, w_1 in enumerate(weights):
            for j, w_2 in enumerate(weights):
                # FIXME: Currently weights are arrays of floats,
                # the following comparison may have a numerical issue.
                if numpy.array_equal(w_2 - w_1, root):
                    pairs.append([i, j])

        return pairs


    def weyl_monodromy(self, root, bp, direction):
        """
        Returns a new root of the segment of an S-wall
        when it crossed a branch cut from bp.
        """
        # TODO: For now, we ASSUME that branch points are 
        # of SQUARE-ROOT type. Need to update this 
        # for more general cases.
        bp_root = bp.positive_roots[0]

        new_root = root - (2 * bp_root * (numpy.dot(root, bp_root))
                           / numpy.dot(bp_root,bp_root))

        return new_root


    def create_root_color_map(self):
        g_roots = list(self.roots)
        n_rts = len(g_roots)
        x = numpy.random.random(size=n_rts) * 200
        y = numpy.random.random(size=n_rts) * 200
        z = numpy.random.random(size=n_rts) * 200
        colors = [
            "#%02x%02x%02x" % (r, g, b) 
            for r, g, b in zip(numpy.floor(x), numpy.floor(y), numpy.floor(z))
        ]
        return {colors[i] : rt for i, rt in enumerate(g_roots)}


    def root_color(self, root):
        if self.root_color_map is None:
            self.root_color_map = self.create_root_color_map()
        root_color_map = self.root_color_map
        return (
            [k for k, v in root_color_map.iteritems()
             if numpy.array_equal(v, root)][0]
        )


class RamificationPoint:
    #def __init__(self, z=None, x=None, i=None, label=None, is_puncture=False):
    def __init__(self, z=None, Ciz=None, x=None, i=None, label=None):
        # z is the numerical value of the PSL2C-transformed z-coordinate.
        self.z = z
        # Ciz is the value of the z-coordinate 
        # before the PSL2C transformation.
        self.Ciz = Ciz
        self.x = x
        self.i = i
        self.label = label
        #self.is_puncture = is_puncture

    def __str__(self):
        return 'z = {}, x = {}, i = {}'.format(self.z, self.x, self.i)

    def __eq__(self, other):
        return self.label == other.label

    def get_json_data(self):
        json_data = {
            'z': ctor2(self.z),
            'Ciz': ctor2(self.Ciz),
            'x': ctor2(self.x),
            'i': ctor2(self.i),
            'label': self.label,
            #'is_puncture': self.is_puncture
        }
        return json_data

    def set_json_data(self, json_data):
        self.z = r2toc(json_data['z'])
        self.Ciz = r2toc(json_data['Ciz'])
        self.x = r2toc(json_data['x'])
        self.i = r2toc(json_data['i'])
        self.label = json_data['label']
        #self.is_puncture = json_data['is_puncture']


class Puncture:
    def __init__(self, z=None, Ciz=None, cutoff=None, label=None):
        # z is the numerical value of the PSL2C-transformed z-coordinate.
        self.z = z
        # Ciz is the value of the z-coordinate 
        # before the PSL2C transformation.
        self.Ciz = Ciz
        self.label = label

    def __eq__(self, other):
        return self.label == other.label


class SWCurve:
    """
    SWCurve.sym_eq is the same curve as defined in the configuration,
    without the PSL2C transformation for the simplicity of its anlysis.

    SWCurve.num_eq is the curve with numerical coefficients &
    after the PSL2C transformation. This is the curve that is used
    in the numerical evolution of S-walls.
    """
    def __init__(self, casimir_differentials=None, g_data=None, 
                 diff_params=None, mt_params=None, ffr=False):
        self.sym_eq = None
        self.num_eq = None

        if ffr is True:
            # Build a cover in the first fundamental representation.
            ffr_eq_str = get_ffr_curve_string(
                casimir_differentials, g_data.type, g_data.rank
            )
            try:
                #self.sym_eq = sympy.simplify(
                #    sympy.sympify(ffr_eq_str).subs(z, Cz)
                #)
                self.sym_eq = sympy.sympify(ffr_eq_str)
            except:
                raise ValueError('syntax error in the Casimir differentials.')
            # NOTE: We apply PSL2C only to the numerical curve
            # for the simplicity of analysis.
            #self.num_eq = self.sym_eq.subs(parameters).evalf()
            Ciz = PSL2C(mt_params, z, inverse=True) 
            self.num_eq = self.sym_eq.subs(z, Ciz).subs(diff_params).evalf()
        else:
            # TODO: Need to build a cover in a general representation
            # from the differentials, using symmetric polynomials.
            logging.warning(
                'class SWCurve with a general representation '
                'is not implemented yet.'
            )



    def get_xs(self, z_0):
        """
        Return a numpy array of x-coordinates over z = z_0.
        """
        if self.num_eq is None:
            raise NotImplementedError

        fx = self.num_eq.subs(z, z_0)
        #xs = sympy.solve(fx, x)
        # FIXME: The following may fail when the curve is not a polynomial.
        sym_poly = sympy.Poly(fx, x, domain='CC')
        coeff_list = map(complex, sym_poly.all_coeffs())
        return numpy.roots(coeff_list)


class SWDiff:
    def __init__(self, v_str, g_data=None, diff_params=None, mt_params=None):
        # sym_v is a SymPy expression. 
        #self.sym_v = sympy.simplify(
        #    sympy.sympify(v_str).subs(z, Ciz) * dCiz
        #)
        self.sym_v = sympy.sympify(v_str)
        # num_v is from sym_v with its parameters 
        # substituted with numerical values.
        # NOTE: We apply PSL2C only to the numerical curve
        # for the simplicity of analysis.
        #self.num_v = self.sym_v.subs(parameters).evalf()
        Ciz = PSL2C(mt_params, z, inverse=True) 
        dCiz = Ciz.diff(z)
        self.num_v = (self.sym_v.subs(z, Ciz)
                      * dCiz).subs(diff_params).evalf()


class SWDataBase(object):
    """
    A class containing the geometric data of a Seiberg-Witten curve
    in the first fundamental representation,
        \lambda^N + \sum_{k=2}^N a_k(z) dz^k \lambda^{N-k}, 
    where \lambda is the Seiberg-Witten differential of the form 
        \lambda = x dz.

    This class also includes ramification points of the curve, and 
    another curve in the representation given in the configuration.

    This is the base class of SWDataWithTrivialization, where 
    the trivialization data of the curve is contained.
    """
    def __init__(self, config):
        self.g_data = None
        self.punctures = []
        self.ffr_curve = None
        self.curve = None
        self.diff = None

        casimir_differentials = {}
        for k, phi_k in parse_sym_dict_str(config['casimir_differentials']):
            casimir_differentials[eval(k)] = phi_k

        self.g_data = GData(config['root_system'], config['representation'])

        diff_params = {}
        for var, val in parse_sym_dict_str(config['differential_parameters']):
            diff_params[var] = sympy.sympify(val)


        if config['mt_params'] is not None:
            mt_params = sympy.sympify(config['mt_params'])
        else:
            mt_params = None

        # PSL2C-transformed z & dz
        #Ciz = PSL2C(mt_params, z, inverse=True) 
        #dCiz = Ciz.diff(z)

        if config['punctures'] is not None:
            punctures_string = config['punctures'].lstrip('[').rstrip(']')
            for p_str in punctures_string.split(','):
                Cipz = sympy.sympify(p_str.strip()).subs(diff_params)
                pz = PSL2C(mt_params, Cipz)
                if pz == oo:
                    npz = oo
                else:
                    npz = complex(pz)
                self.punctures.append(
                    Puncture(
                        z=npz, Ciz=Cipz,
                        cutoff=config['size_of_puncture_cutoff'],
                        label='puncture #{}'.format(len(self.punctures))
                    )
                )

        self.ffr_curve = SWCurve(
            casimir_differentials=casimir_differentials, 
            g_data=self.g_data,
            diff_params=diff_params,
            mt_params=mt_params,
            ffr=True,
        )
        logging.info(
            'Seiberg-Witten curve in the 1st fundamental '
            'representation: {} = 0.\n(numerically {}=0.)'
            .format(sympy.latex(self.ffr_curve.sym_eq),
                    sympy.latex(self.ffr_curve.num_eq))
        )
        # TODO: SWCurve in a general representation.
        if self.g_data.fundamental_representation_index == 1:
            self.curve = self.ffr_curve
        else:
            logging.warning(
                'Seiberg-Witten curve in a general representation '
                'is not implemented yet.'
            )
            self.curve = None


        # Seiberg-Witten differential
        self.diff = SWDiff(
            'x',
            g_data=self.g_data,
            diff_params=diff_params,
            mt_params=mt_params,
        )

        logging.info('\nSeiberg-Witten differential: %s dz\n',
                     sympy.latex(self.diff.num_v))

        logging.info(
            "Calculating ramification points of the Seiberg-Witten curve "
            "in the first fundamental rep."
        )
        self.ffr_ramification_points = get_ramification_points(
            curve=self.ffr_curve, 
            diff_params=diff_params,
            mt_params=mt_params,
            accuracy=config['accuracy'], 
            punctures=self.punctures,
            method=config['ramification_point_finding_method'],
        )


    def get_aligned_xs(self, z_0):
        """
        Returns (aligned_ffr_xs, aligned_xs), where each element is
        a numpy array of x-coordinates of the fibers over z.
        The order of x's is the same as the order of the weights
        in g_data.weights.
        """
        algebra_type = self.g_data.type
        algebra_rank = self.g_data.rank
        fund_rep_index = self.g_data.fundamental_representation_index

        # First order x's of the first fundamental cover
        # according to the order of ''g_data.weights'',
        # then construct the list of x's for the given representation
        # ordered according to weights.
        # NOTE: does this correspond to the 7th irrep for E7?
        #       We need that one for that algebra
        ffr_xs = self.ffr_curve.get_xs(z_0) 

        if algebra_type == 'A':
            # Can consider ffr_xs to be aligned according to ffr_weights,
            # [(1, 0, 0, 0, 0, 0),
            #  (0, 1, 0, 0, 0, 0),
            #  ...,
            #  (0, 0, 0, 0, 0, 1)].
            aligned_ffr_xs = ffr_xs

            if fund_rep_index == 1:
                xs = aligned_ffr_xs
            else:
                xs = self.get_xs_of_weights_from_ffr_xs(aligned_ffr_xs)

        elif algebra_type == 'D':
            # Align ffr_xs according to ffr_weights,
            # [(1, 0, 0, 0, 0),
            #  (0, 1, 0, 0, 0),
            #  ...,
            #  (0, 0, 0, 0, 1),
            #  (-1, 0, 0, 0, 0),
            #  ...
            #  (0, 0, 0, 0, -1)]      
            sorted_ffr_xs = numpy.array(
                sorted(ffr_xs, key=lambda z: (z.real, z.imag), reverse=True,)
            )
            # Pick x's corresponding to the positive weights.
            # The order among the positive x's is arbitrary.
            positive_xs = sorted_ffr_xs[:algebra_rank]
            # Then pick an x corresponding to each negative weight
            # aligned according to the positive x's.
            negative_xs = numpy.zeros_like(positive_xs)
            for nx in sorted_ffr_xs[algebra_rank:]:
                difference = numpy.fromiter(
                    (abs(px - (-nx)) for px in positive_xs),
                    dtype=float,
                )
                j = difference.argsort()[0]
                # Check the pairing of positive and negative x's.
                px_j = positive_xs[j]
                if numpy.isclose(px_j, -nx) is False:
                    warn("get_ordered_xs(): No pairing of x's in the D-type, "
                         "({}, {}) != (x, -x).".format(px_j, nx))
                else:
                    # Put the negative x at the same index
                    # as its positive pair.
                    negative_xs[j] = nx
            aligned_ffr_xs = numpy.concatenate((positive_xs, negative_xs))

            if fund_rep_index == 1:
                xs = aligned_ffr_xs
            else:
                xs = self.get_xs_of_weights_from_ffr_xs(aligned_ffr_xs)

        elif algebra_type == 'E':
            if algebra_rank == 6:
                ffr_weights_list = list(self.g_data.ffr_weights)
                aligned_ffr_xs = sort_sheets_for_e_6_ffr(
                    ffr_xs, ffr_weights_list
                )
                if fund_rep_index == 1:
                    xs = aligned_ffr_xs
                else:
                    #xs = self.get_xs_of_weights_from_ffr_xs(aligned_ffr_xs)
                    raise NotImplementedError
            elif algebra_rank == 7:
                raise NotImplementedError
     
        return (aligned_ffr_xs, xs)


    def get_xs_of_weights_from_ffr_xs(self, ffr_xs):
        g_data = self.g_data
        xs = numpy.zeros(len(g_data.weights), dtype=complex)

        if g_data.type == 'A' or g_data.type == 'D':
            for i, cs in enumerate(g_data.weight_coefficients):
                for j, c_j in enumerate(cs):
                    xs[i] += c_j * ffr_xs[j]
        else:
            raise NotImplementedError

        return xs

# E_6 curve strings
tau_str = 't + 1/t + {u_6}'
q_1_str = (
'270*x^(15) + 342*({u_1})*x^(13) + 162*({u_1})^2*x^(11) - 252*({u_2})*x^(10)'  
'+ (26*({u_1})^3 + 18*({u_3}))*x^9 - 162*({u_1})*({u_2})*x^8' 
'+ (6*({u_1})*({u_3}) - 27*({u_4}))*x^7' 
'- (30*({u_1})^2*({u_2}) - 36*({u_5}))*x^6' 
'+ (27*({u_2})^2 - 9*({u_1})*({u_4}))*x^5' 
'- (3*({u_2})*({u_3}) - 6*({u_1})*({u_5}))*x^4' 
'- 3*({u_1})*({u_2})^2*x^3 - 3*({u_2})*({u_5})*x - ({u_2})^3'
)
q_2_str = '1/(2*x^3)*(({q_1})^2 - ({p_1})^2*({p_2}))'
p_1_str = (
'78*x^10 + 60*({u_1})*x^8 + 14*({u_1})^2*x^6 - 33*({u_2})*x^5 + 2*({u_3})*x^4' 
'- 5*({u_1})*({u_2})*x^3 - ({u_4})*x^2 - ({u_5})*x - ({u_2})^2'
)
p_2_str = (
'12*x^10 + 12*({u_1})*x^8 + 4*({u_1})^2*x^6 - 12*({u_2})*x^5 + ({u_3})*x^4' 
'- 4*({u_1})*({u_2})*x^3 - 2*({u_4})*x^2 + 4*({u_5})*x  + ({u_2})^2'
)

def get_ffr_curve_string(casimir_differentials, g_type, g_rank):
    """
    Construct a Seiberg-Witten curve in the 1st fundamental representation
    using Casimir differentials.
    """
    cs = []
    if g_type == 'A':
        N = g_rank + 1
        for k, phi_k in casimir_differentials.iteritems():
            cs.append([k, phi_k])

    elif g_type == 'D':
        N = 2 * g_rank
        for k, phi_k in casimir_differentials.iteritems():
            if k % 2 != 0:
                raise ValueError(
                    'phi_{} = {} dz^k'.format(k, phi_k) + 
                    'is an incorrect casimir differential '
                    'for a D-type curve.' 
                )
            else:
                cs.append([k, phi_k])

    elif g_type == 'E':
        phi = casimir_differentials
        # u_(1, 2, 3, 4, 5) = phi[2, 5, 6, 8, 9, 12]
        if g_rank == 6:
            tau = tau_str.format(u_6=phi[12])
            q_1 = q_1_str.format(u_1=phi[2], u_2=phi[5], u_3=phi[6],
                                 u_4=phi[8], u_5=phi[9])
            p_1 = p_1_str.format(u_1=phi[2], u_2=phi[5], u_3=phi[6],
                                 u_4=phi[8], u_5=phi[9])
            p_2 = p_2_str.format(u_1=phi[2], u_2=phi[5], u_3=phi[6],
                                 u_4=phi[8], u_5=phi[9])
            q_2 = q_2_str.format(q_1=q_1, p_1=p_1, p_2=p_2)
            curve_str = (
                '(1/2)*x^3*({tau})^2 - ({q_1})*({tau}) + ({q_2})'
                .format(tau=tau, q_1=q_1, q_2=q_2)
            )
            return curve_str

    else:
        raise NotImplemented(
            'get_ffr_curve_string(): construction of a Seiberg-Witten curve '
            'of g = {}_{} is not implemented.'.format(g_type, g_rank)
        )

    # g_type == 'A' or g_type == 'D':
    curve_str = 'x^{} '.format(N)
    for k, c_k in cs:
        curve_str += '+ ({}) '.format(c_k)
        if k != N:
            curve_str += '* x^{}'.format(N-k)

    return curve_str


def get_ramification_points(
    curve=None, 
    diff_params=None, 
    mt_params=None,
    accuracy=None, 
    punctures=None,
    method=None,
):
    if curve.sym_eq is None:
        raise NotImplementedError

    if method == 'discriminant':
        sols = get_ramification_points_using_discriminant(
            curve=curve, 
            diff_params=diff_params, 
            mt_params=mt_params,
            accuracy=accuracy, 
            punctures=punctures,
        )
    elif method == 'system_of_eqs':
        sols = get_ramification_points_using_system_of_eqs(
            curve=curve, 
            diff_params=diff_params, 
            mt_params=mt_params,
            accuracy=accuracy, 
            punctures=punctures,
        )
    else:
        raise ValueError(
            'Unknown or no method set to find ramification points.\n'
            'Set ramification_point_finding_method = '
            '[discriminant|system_of_eqs] in the configuration.'
        )

    ramification_points = []

    for z_i, (x_j, m_x) in sols:
        label = ('ramification point #{}'
                 .format(len(ramification_points)))
        rp = RamificationPoint(
            z = PSL2C(mt_params, z_i, numerical=True),
            Ciz=complex(z_i), 
            x=complex(x_j), 
            i=m_x, 
            label=('ramification point #{}'
                   .format(len(ramification_points)))
        )
        logging.info("{}: z = {}, x = {}, i = {}."
                     .format(label, rp.z, rp.x, rp.i))
        ramification_points.append(rp)

    return ramification_points


def get_ramification_points_using_system_of_eqs(
    curve=None, 
    diff_params=None, 
    mt_params=None,
    accuracy=None, 
    punctures=None,
):
    sols = []
    f = curve.sym_eq
    # Make f into the form of f_n/f_d
    f_n, f_d = sympy.cancel(f).as_numer_denom()

    d_x_f_n, d_x_f_d = sympy.cancel(f.diff(x)).as_numer_denom()

    subs_dict = copy.deepcopy(diff_params)
    
    # NOTE: solve_poly_system vs. solve
    #sols = sympy.solve_poly_system([f, f.diff(x)], z, x)
    #sols = sympy.solve([f, f.diff(x)], z, x)
    z_x_s = sage_subprocess.solve_system_of_eqs(
        [f_n.subs(subs_dict), d_x_f_n.subs(subs_dict)],
        precision = ROOT_FINDING_PRECISION,
    )
    for z_i, x_i in z_x_s:
        # Check if z_i is one of the punctures.
        is_puncture = False
        for p in punctures:
            if abs(z_i - p.Ciz) < accuracy:
                is_puncture = True
        if is_puncture:
            continue

        subs_dict[z] = z_i
        f_x_cs = [c.evalf(subs=subs_dict, n=ROOT_FINDING_PRECISION) 
                  for c in sympy.Poly(f, x).all_coeffs()]
        f_x_coeffs = [mpmath.mpc(*c.as_real_imag()) for c in f_x_cs]
        f_x_roots = None
        polyroots_maxsteps = ROOT_FINDING_MAX_STEPS
        polyroots_extra_precision = ROOT_FINDING_PRECISION
        while f_x_roots is None:
            try:
                f_x_roots = mpmath.polyroots(
                    f_x_coeffs,
                    maxsteps=polyroots_maxsteps,
                    extraprec=polyroots_extra_precision
                )
            except NoConvergence:
                logging.warning(
                    'mpmath.polyroots failed; increase maxsteps & '
                    'extraprec by 10.'
                )
                polyroots_maxsteps += 10
                polyroots_extra_precision += 10

        m_x = 0
        for x_j in f_x_roots:
            if abs(x_i - x_j) < accuracy:
                m_x += 1

        sols.append([z_i, (x_i, m_x)])

    return sols
            


def get_ramification_points_using_discriminant(
    curve=None, 
    diff_params=None, 
    mt_params=None,
    accuracy=None, 
    punctures=None,
):
    sols = []
    f = curve.sym_eq
    # Make f into the form of rf = f_n/f_d
    rf = sympy.cancel(f)
    f_n, f_d = rf.as_numer_denom()
    subs_dict = copy.deepcopy(diff_params)

    # Find the roots of D(z), the discriminant of f(x, z)
    # as a polynomial of x. 
    D_z = sympy.discriminant(f_n, x)
    D_z_n, D_z_d = sympy.cancel(D_z).as_numer_denom()
    D_z_n_P = sympy.Poly(D_z_n, z)
    cs = [
        c_sym.evalf(
            subs=subs_dict, n=ROOT_FINDING_PRECISION
        ).as_real_imag()
        for c_sym in D_z_n_P.all_coeffs()
    ]
    D_z_n_P_coeffs = [mpmath.mpc(*c) for c in cs]
    # Increase maxsteps & extraprec when root-finding fails.
    D_z_roots = None
    polyroots_maxsteps = ROOT_FINDING_MAX_STEPS
    polyroots_extra_precision = ROOT_FINDING_PRECISION
    while D_z_roots is None:
        try:
            D_z_roots = mpmath.polyroots(
                D_z_n_P_coeffs, 
                maxsteps=polyroots_maxsteps,
                extraprec=polyroots_extra_precision,
            )
        except NoConvergence:
            logging.warning(
                'mpmath.polyroots failed; increase maxsteps & extraprec '
                'by 10.'
            )
            polyroots_maxsteps += 10
            polyroots_extra_precision += 10

    is_same_z = lambda a, b: abs(a - b) < accuracy
    gathered_D_z_roots = gather(D_z_roots, is_same_z)  

    # Find the roots of f(x, z=z_i) for the roots {z_i} of D(z).
    for z_i, zs in gathered_D_z_roots.iteritems():
        # m_z is the multiplicity of z_i.
        m_z = len(zs)
        # Check if z_i is one of the punctures.
        is_puncture = False
        for p in punctures:
            if abs(z_i - p.Ciz) < accuracy:
                is_puncture = True
        if is_puncture:
            continue
                
        subs_dict[z] = z_i
        f_x_cs = [c.evalf(subs=subs_dict, n=ROOT_FINDING_PRECISION) 
                  for c in sympy.Poly(f, x).all_coeffs()]
        f_x_coeffs = [mpmath.mpc(*c.as_real_imag()) for c in f_x_cs]
        f_x_roots = None
        while f_x_roots is None:
            try:
                f_x_roots = mpmath.polyroots(
                    f_x_coeffs,
                    maxsteps=polyroots_maxsteps,
                    extraprec=polyroots_extra_precision
                )
            except NoConvergence:
                logging.warning(
                    'mpmath.polyroots failed; increase maxsteps & '
                    'extraprec by 10.'
                )
                polyroots_maxsteps += 10
                polyroots_extra_precision += 10

        # In general x-roots have worse errors.
        is_same_x = lambda a, b: abs(a - b) < accuracy/1e-2
        gathered_f_x_roots = gather(f_x_roots, is_same_x)
        for x_j, xs in gathered_f_x_roots.iteritems():
            # m_x is the multiplicity of x_j.
            m_x = len(xs)
            if m_x == 1:
                continue

            sols.append([z_i, (x_j, m_x)])

    return sols


def find_xs_at_z_0(sw_data, z_0, x_0=None, num_x=1, ffr=False):
    """
    Get x's above z_0 and return the num_x of them 
    which are nearest to x_0.
    """
    
    xs_at_z_0 = sw_data.get_sheets_at_z(z_0, ffr=ffr).values()
    if x_0 is None:
        return xs_at_z_0
    else:
        return sorted(xs_at_z_0,
                      lambda x1, x2: cmp(abs(x1 - x_0), abs(x2 - x_0)))[:num_x]
   

def get_local_sw_diff(sw, ramification_point, ffr=None):
    rp = ramification_point
    if ffr is None or ffr is False:
        num_eq = sw.curve.num_eq
        num_v = sw.diff.num_v
    elif ffr is True:
        num_eq = sw.ffr_curve.num_eq
        num_v = sw.diff.num_v

    # use Dz = z - rp.z & Dx = x - rp.x
    Dz, Dx = sympy.symbols('Dz, Dx')
    local_curve = (
        num_eq.subs(x, rp.x+Dx).subs(z, rp.z+Dz)
        .series(Dx, 0, rp.i+1).removeO()
        .series(Dz, 0, 2).removeO()
    )
    # curve_at_rp = a(z - rp.z) + b(x - rp.x)^(rp.i)
    a = local_curve.n().coeff(Dz).coeff(Dx, 0)
    b = local_curve.n().coeff(Dx**rp.i).coeff(Dz, 0)
    # Dx = Dx(Dz)
    Dx_Dz = (-(a/b)*Dz)**sympy.Rational(1, rp.i)
    local_diff = (
        num_v.subs(x, rp.x+Dx_Dz).subs(z, rp.z+Dz)
        .series(Dz, 0, 1).removeO()
    )
    # get the coefficient and the exponent of the leading term
    (diff_c, diff_e) = local_diff.leadterm(Dz)
    if diff_e == 0:
        # remove the constant term from the local_diff
        local_diff -= local_diff.subs(Dz, 0)
        (diff_c, diff_e) = local_diff.leadterm(Dz)

    return (complex(diff_c.n()), diff_e)


def null_weight_triples(weights):
    null_vec = numpy.array([0 for i in range(len(list(weights[0])))])
    null_triples = []
    for i, j, k in combinations(range(len(weights)), 3):
        w_i = weights[i]
        w_j = weights[j]
        w_k = weights[k]
        # FIXME: weights are in general arrays of floats, so
        # there may be a numerical issue in the following comparison.
        if (w_i + w_j + w_k == null_vec):
            null_triples.append([i,j,k])

    return sorted(null_triples)


def null_sheet_triples(sheets):
    null_triples = []
    for x_i, x_j, x_k in combinations(sheets, 3):
        if (abs(x_i + x_j + x_k) < SHEET_NULL_TOLERANCE):
            null_triples.append([x_i, x_j, x_k])

    return sorted(null_triples)


def get_quintets(e, null_triples):
    """ Return the quintets of triples for the given weight/sheet."""
    return [t for t in null_triples if e in t]


def quintet_contained(e, quintet):
    """
    Check whether a weight/sheet e
    is contained in a quintet of triples
    Return 0 for 'No' and '1' for 'Yes'
    """
    ans = 0
    for t in quintet:
        if e in t:
            ans = 1
            break
    return ans


def sort_sheets_for_e_6_ffr(sheets, weights):
    """
    Return the list of sheets sorted according to the list of weights.
    The output is a list such that sheets[i] will correspond to weights[i].
    """
    sorted_sheets = [None for w in weights]
    x_0 = sheets[0]

    n_w_triples = null_weight_triples(weights)
    n_s_triples = null_sheet_triples(sheets)

    # Start sorting
    sorted_sheets[0] = x_0

    # The quintet of triples of \mu_0
    q_0 = get_quintets(0, n_w_triples)

    # The quintet of SHEET triples of x_0
    s_q_0 = get_quintets(x_0, n_s_triples)

    # Get the list of sheets appearing in the quintet s_q_0
    # The weyl symmetry allows us to fix the these
    known_sheets = [x_0]
    for i in range(NULL_TRIPLES_INDIVIDUAL):
        # Get the (unordered) pair of sheets [x_i, x_j] 
        # from each triple [x_0, x_i, x_j]
        s_pair = [s for s in s_q_0[i] if s!=x_0]
        # Get the (unordered) pair of weight-labels [i, j] 
        # from each triple [0, i, j]
        w_pair = [k for k in q_0[i] if k!=0]

        sorted_sheets[w_pair[0]] = s_pair[0]
        sorted_sheets[w_pair[1]] = s_pair[1]

        known_sheets.append(s_pair[0])
        known_sheets.append(s_pair[1])

    # Get the list of weights appearing in the quintet q_0
    known_weights = [0]
    for t in q_0:
        for i in t:
            if i in known_weights:
                continue
            else:
                known_weights.append(i)

    missing_weights = [i for i in range(len(weights)) 
                                        if not i in known_weights]
    missing_sheets = [x for x in range(len(sheets)) 
                                        if not i in known_sheets]
    
    # List all the combos of which WEIGHT quintets 
    # must/must not contain all missing WEIGHTS
    weight_combos = [[quintet_contained(j, get_quintets(i, n_w_triples)) 
                        for i in known_weights] for j in missing_weights]

    # List all the combos of which SHEET quintets 
    # must/must not contain all missing SHEETS
    sheet_combos = [[quintet_contained(x, get_quintets(y, n_s_triples)) 
                        for y in known_sheets] for x in missing_sheets]

    # Now match the patterns of inclusion in the quintets
    # between missing weights and missing sheets.
    # When the patterns match, assign the corresponding 
    # sheet to the list of sorted ones.
    for i in range(len(missing_sheets)):
        s_combo = sheet_combos[i]
        for j in range(len(missing_weights)):
            w_combo = weight_combos[j]
            if s_combo == w_combo:
                sorted_sheets[j] = missing_sheets[i]
            else:
                pass


    # A basic check that we didn't pick a sheet twice
    if len(sorted_sheets) == len(delete_duplicates(sorted_sheets)):
        pass
    else:
        raise ValueError('Something is wrong with the sorting of sheets')

    return sorted_sheets
