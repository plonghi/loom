import numpy
import logging
import pdb
import sympy

from cmath import exp, pi, phase
from sympy import oo
from numpy.linalg import matrix_rank
from itertools import combinations
from pprint import pprint
from heapq import nsmallest

from geometry import SWDataBase
#from misc import n_unique
from misc import n_remove_duplicate

x, z = sympy.symbols('x z')


# TODO: set both of the following automatically: e.g. using the
# minimal_distance attribute of the SW fibration
### number of steps used to track the sheets along a leg 
### the path used to trivialize the cover at any given point
N_PATH_TO_PT = 100
### number of steps for each SEGMENT of the path around a 
### branching point (either branch-point, or irregular singularity)
N_PATH_AROUND_PT = 60
#N_PATH_AROUND_PT = 100
### Number of times the tracking of sheets is allowed to automatically zoom in.
MAX_ZOOM_LEVEL = 2
ZOOM_FACTOR = 10

### Tolerance for recognizing colliding sheets at a branch-point
BP_PROXIMITY_THRESHOLD = 0.05


class BranchPoint:
    """
    The BranchPoint class.

    This class is strictly related to the 
    cover corresponding to the first fundamental
    representation.

    Attributes
    ----------

    z :
        The position of the branch point on the z-plane

    trivialization : 
        The trivialization of the cover to which the 
        branch point is associated.

    groups :
        A list of groups of sheets which collide together
        at the branch point.

    singles :
        The list of sheets which do not collide with any
        other sheet.

    enum_sh :
        The enumerated sheets at the branch point. 
        A list of pairs [i, x] where i is the sheet 
        identifier referring to the reference sheets 
        of the trivialization class; x is the corresponding
        coordinate in the fiber above the branch point.

    path_to_bp - UNAVAILABLE :
        A path running from the basepoint of the trivialization
        to the branch point without crossing any branch cut.
    
    sheet_tracks_to_bp - UNAVAILABLE :
        A list of sheet tracks, i.e. the x-values of each
        sheet as it is tracked along a path that runs to
        the branch point, to determine collision structure 
        of the various sheets.
    
    positive_roots :
        A minimal list of positive roots characterizing the 
        groups of colliding sheets at the branch point.
    
    path_around_bp - UNAVAILABLE :
        A path encircling the branch point and no one else,
        used to compute the monodromy.
    
    sheet_tracks_around_bp - UNAVAILABLE :
        A list of sheet tracks, i.e. the x-values of each
        sheet as it is tracked along a path that runs around 
        the branch point, to determine the monodromy.
    
    monodromy : 
        The monodromy matrix acting on the column vector
        of sheets (hence, acting FROM the left).
        Sheets are ordered according to the reference 
        sheets of the trivialization.
    
    order : 
        At a branch point, the dual of the higgs field 
        lies on the boundary of a Weyl chamber.
        In general, it will li at the intersection of
        k of the walls delimiting the chamber.
        The order of the branch point is then k + 1.

    ffr_ramification_points :
        A list of all ramification point objects, which 
        lie in the fiber above the branch point.

    """
    def __init__(self, z=None):
        self.z = z

        self.groups = None 
        self.singles = None
        self.enum_sh = None
        self.positive_roots = None 
        self.order = None

        self.monodromy = None
        self.ffr_ramification_points = None
        self.label = None

    def print_info(self):
        print(
            "---------------------------------------------------------\n"
            "Branch Point at z = {}\n"
            "---------------------------------------------------------"
            .format(self.z)
        )
        for key, value in vars(self).iteritems():
            print("{}:".format(key))
            pprint(value)

class IrregularSingularity:
    """
    The IrregularSingularity class.
    Just a container of information.
    Strictly related to the first fundamental representation cover.
    """
    def __init__(self, z=None, label=None):
        self.z = z
        self.label=label
        self.monodromy = None
        
    def print_info(self):
        print(
            "---------------------------------------------------------\n"
            "Irregular singularity at z = {}\n"
            "---------------------------------------------------------"
            .format(self.z)
        )
        for key, value in vars(self).iteritems():
            print("{}:".format(key))
            pprint(value)


# TODO: Use g_data.weights at the base point as labels of sheets,
# instead of integer indicies. Just a conceptual issue, because
# the integer indicies are labeling g_data.weights in the same order.
# PL: not sure if we want to do that: for a human interface, 
# labeling by integers is much more readable.
class SWDataWithTrivialization(SWDataBase):
    """
    All branch cuts are assumed to run vertically, emanating
    upwards from branch points and irregular singularities.

    Arguments
    ---------
    
    sw_data : 
        an object of the type SWData, whose attribute 'curve' 
        should correspond to the curve in the FIRST fundamental
        representation of the Lie algebra
    
    ffr_ramification_points : 
        a list of objects of the type RamificationPoint, corresponding
        to the given Seiberg-Witten curve in the first fundamental rep.

    Attributes & Methods
    --------------------

    base_point : 
        the base point of the trivialization

    reference_ffr_xs :
        a list of x's 
            [x_0, x_1, ..., x_i, ...]
        where 'i' is an integer label for the sheet,
        and 'x' is its position in the fiber of T^*C 
        over the basepoint. This is aligned with 
        g_data.ffr_weights.

    get_sheets_at_z(z) :
        this method returns the set of sheets and their integer label 
        identifier at any point 'z' on the C-plane.
        The labels are consistent with those at the basepoint.
        To get the corresponding weights, of the first fundamental 
        representation, use g_data.weights[i].
        The output looks like this
        {0 : x_0, ... , i : x_i, ...}
    """
    # NOTE: I am assuming that branch points NOR irregular singularities 
    # overlap vertically.
    # This should be guaranteed by the automatic rotation of 
    # the z-plane which is performed before calling this class.
    def __init__(self, config,):
        super(SWDataWithTrivialization, self).__init__(config)
        self.accuracy = config['accuracy']
        self.branch_points = []
        # FIXME: Mark each puncture in the config.ini as being (ir)regular,
        # or analyze all punctures to determine the irregularity.
        # Very important: once we do this, we must make sure that the
        # algorithm of automatic z-rotation checks BOTH irregulars and regulars,
        # because we don't want either of them to be aligned 
        # vertically with a branch point or with each other, for 
        # trivialization purposes (even if regulars don't emanate cuts).
        self.irregular_singularities = []

        # z-coords of branch points.
        bpzs = n_remove_duplicate(
            [r.z for r in self.ffr_ramification_points if r.z != oo],
            self.accuracy,
        )

        # z-coords of irregular singularities.
        iszs = n_remove_duplicate(
            [p.z for p in self.punctures if p.z != oo],
            self.accuracy,
        )
        
        # Automatically choose a basepoint, based on the positions of
        # both branch points and irregular singularities
        all_points_z = bpzs + iszs
        n_critical_loci = len(all_points_z)
        
        if n_critical_loci > 1:
            all_distances = [abs(x - y) for x in all_points_z
                                                for y in all_points_z]
            max_distance = max(all_distances)
            # Minimun mutual distance among all the
            # branch points/punctures.
            non_zero_distances = [x for x in all_distances
                                  if abs(x) > self.accuracy]
            self.min_distance = min(non_zero_distances)
            horizontal_distances = [abs(x.real - y.real) for x in all_points_z
                                                        for y in all_points_z]
            self.min_horizontal_distance = min(
                    [x for x in horizontal_distances if abs(x) > self.accuracy]
                )
            
        elif n_critical_loci == 1:
            # If there is only one branching locus, we still
            # need to set distance scales, as these will be used to 
            # circumvent the branch locus when constructing paths 
            # to trivializae the cover, as well as to fix a basepoint
            # for the trivialization
            max_distance = 3.0
            self.min_distance = max_distance
            self.min_horizontal_distance = max_distance

        elif n_critical_loci == 0:
            raise Exception('Must have at least one critical locus on C.')

         
        center = sum([z_pt for z_pt in all_points_z]) / n_critical_loci
        self.base_point = center - 1j * max_distance

        ### Alternative fix for only one branch locus
        ###       
        # # Minimun mutual distance among all the
        # # branch points/punctures.
        # non_zero_distances = [x for x in all_distances
        #                       if abs(x) > self.accuracy]
        # if n_critical_loci == 1:
        #     # hacky way of dealing with special case of just
        #     # one branch point
        #     self.min_distance = 0.1
        #     self.base_point = center - 0.2j
        # else:
        #     self.min_distance = min(non_zero_distances)
        ###


        #print 'all points {}'.format(all_points_z)
        #print 'all distances: {}'.format(non_zero_distances)
        #print self.min_distance
        # Fix reference x's at the basepoint.
        # These sheets are aligned in the order of
        # sw.g_data.weights, i.e. reference_sheets[i]
        # is the value of x corresponding to 
        # sw.g_data.weights[i].
        logging.info(
            "Getting aligned x's at the base point z = {}."
            .format(self.base_point)
        )
        self.reference_ffr_xs, self.reference_xs = self.get_aligned_xs(
            self.base_point,
        )

        ### Construct the list of branch points
        for i, z_bp in enumerate(bpzs):
            bp = BranchPoint(z=z_bp)
            bp.label = 'Branch point #{}'.format(i)
            self.analyze_branch_point(bp)
            if bp.order > 1:
                # only add if there are any positive roots associated
                # otherwise may be an accidental BP
                # FIXME: Must handle also accidental BP
                # for example a point like F~ z + x^2(1+x^2) can happen in D-type
                # and will have no obvious monodromy. Need to deal with it. 
                self.branch_points.append(bp)

        ### Construct the list of irregular singularities
        for j, z_irr_sing in enumerate(iszs):
            irr_sing = IrregularSingularity(
                                z=z_irr_sing, label='Irr.Sing. #{}'.format(j)
                                )
            self.analyze_irregular_singularity(irr_sing)
            self.irregular_singularities.append(irr_sing)

        ### Analyze ramification points
        for bp in self.branch_points:
            for rp in bp.ffr_ramification_points:
                self.analyze_ffr_ramification_point(rp)

        
    # TODO: Need to implement tracking without using aligned x's?
    # PL: Do we actually need to?
    def get_sheets_along_path(self, z_path, is_path_to_bp=False, ffr=False,
                                ffr_xs_0=None, zoom_level=MAX_ZOOM_LEVEL,
                                accuracy=None, ffr_sheets_along_path=None,
                            ):
        """
        Tracks the sheets along a path.
        It checks at each step that tracking is successful,
        meaning that all sheets can be distinguished correctly.
        This would fail if we choose a path ending on a branch-point.
        For tracking roots as we run into a branch point, one should
        set the variable 'is_path_to_bp=True', and the check for 
        sheets becoming too similar will be ignored altogether.
        If tracking fails, an attempt will be made to 'zoom in',
        up to a certain number of times.
        If zooming also fails, the tracking will take into account 
        the first derivative of sheets and match them according to it.
        """       
        g_data = self.g_data
        if accuracy==None:
            accuracy = self.accuracy
        # If the initial sheets are unspecified, 
        # the initial point should be the basepoint of the trivialization 
        if ffr_xs_0 == None:
            if abs(z_path[0] - self.base_point) < self.accuracy:
                ffr_xs_0 = self.reference_ffr_xs
                xs_0 = self.reference_xs
            else:
                raise Exception('Must specify initial sheets for tracking.')
        logging.info('Zooming to level {}'.format(zoom_level))
        ### Each element is a sheet, which is a list of x's along the path.
        ### Initialized with reference_xs.
        ### TODO: set each element to an integer rather than a float.
        if ffr_sheets_along_path==None:
            ffr_sheets_along_path = [[x] for x in ffr_xs_0]
        
        for i, z in enumerate(z_path):
            if any(isinstance(i, list) for i in ffr_xs_0):
                print 'ffr_xs_0 = {}'.format(ffr_xs_0)
            near_degenerate_branch_locus = False
            if is_path_to_bp is True and abs(z - z_path[-1]) < self.accuracy:
                near_degenerate_branch_locus = True
            ffr_xs_1, xs_1 = self.get_aligned_xs(
                    z, 
                    near_degenerate_branch_locus=near_degenerate_branch_locus
                )

            if is_path_to_bp == False:
                sorted_ffr_xs = get_sorted_xs(ffr_xs_0, ffr_xs_1, 
                                            accuracy=accuracy,
                                            check_tracking=True, index=i,
                                            z_0=z_path[i-1], z_1=z_path[i],
                                            g_data=g_data,
                                        )
            elif near_degenerate_branch_locus is False:
                sorted_ffr_xs = get_sorted_xs(ffr_xs_0, ffr_xs_1,
                                            accuracy=accuracy,
                                            check_tracking=True,
                                            g_data=g_data,
                                        )
            else:
                sorted_ffr_xs = get_sorted_xs(ffr_xs_0, ffr_xs_1,
                                            accuracy=accuracy,
                                            check_tracking=False,
                                            g_data=g_data,
                                        )
            if sorted_ffr_xs == 'sorting failed':
                if zoom_level > 0:
                    delta_z = (z_path[i] - z_path[i-1])/ZOOM_FACTOR
                    zoomed_path = [z_path[i-1] + j*delta_z 
                                            for j in range(ZOOM_FACTOR+1)]
                    sheets_along_zoomed_path = self.get_sheets_along_path(
                                    zoomed_path, 
                                    is_path_to_bp=near_degenerate_branch_locus,
                                    ffr=True,
                                    ffr_xs_0=ffr_xs_0,
                                    zoom_level=(zoom_level-1),
                                    accuracy=(accuracy/ZOOM_FACTOR),
                                    ffr_sheets_along_path=ffr_sheets_along_path,
                                )
                    sorted_ffr_xs = [
                            zoom_s[-1] for zoom_s in sheets_along_zoomed_path
                        ]
                    # for j, s_j in enumerate(ffr_sheets_along_path):
                    #     s_j += sorted_ffr_xs[j]

                else:
                    old_ffr_xs = [s[-2] for s in ffr_sheets_along_path]
                    delta_xs = [ffr_xs_0[j] - old_ffr_xs[j] 
                                                for j in range(len(ffr_xs_0))]
                    sorted_ffr_xs = sort_xs_by_derivative(ffr_xs_0, ffr_xs_1, 
                                                        delta_xs, self.accuracy)
                    if sorted_ffr_xs == 'sorting failed':
                        raise Exception(
                            '\nCannot track the sheets!\n'
                            'Probably passing too close to a branch point '
                            'or a puncture. Try increasing N_PATH_TO_PT '
                            'or N_PATH_AROUND_PT, or MAX_ZOOM_LEVEL.'
                        )
            else:
                # this is just the ordinary step, where we add the 
                # latest value of ordered sheets
                for j, s_j in enumerate(ffr_sheets_along_path):
                    s_j.append(sorted_ffr_xs[j])
            

        ### the result is of the form [sheet_path_1, sheet_path_2, ...]
        ### where sheet_path_i = [x_0, x_1, ...] are the fiber coordinates
        ### of the sheet along the path
        if ffr is True:
            return ffr_sheets_along_path
        elif ffr is False:
            sheets_along_path = []
            for s in ffr_sheets_along_path:
                sheets_along_path.append(
                    [self.get_xs_of_weights_from_ffr_xs(ffr_x) for ffr_x in s]
                )
            return sheets_along_path


    def get_sheets_at_z(self, z_pt, g_data=None, ffr=False):
        """
        Returns a dict of (sheet_index, x) at a point ''z_pt'', 
        which cannot be a branch point or a singularity.
        """
        z_path = get_path_to(z_pt, self)
        sheets = self.get_sheets_along_path(z_path, ffr=ffr)
        final_xs = [s_i[-1] for s_i in sheets]
        final_sheets = {i : x for i, x in enumerate(final_xs)}
        return final_sheets

    
    ### TODO: Review this method.
    def get_sheet_monodromy(self, z_path):
        """
        Compares the x-coordinates of sheets at the 
        beginning and at the end of a CLOSED path.
        Returns a permutation matrix, expressed in 
        the basis of reference sheets, such that
        new_sheets = M . old_sheets
        """
        logging.debug(
            "Analyzing the monodromy around a closed path "
            "of length {}.".format(len(z_path))
        )
        initial_xs = self.reference_xs
        initial_sheets = [[i, x] for i, x in enumerate(initial_xs)]
        final_xs = [sheet_i[-1] 
                    for sheet_i in self.get_sheets_along_path(z_path)]
        final_sheets = [[i, x] for i, x in enumerate(final_xs)]

        ### Now we compare the initial and final sheets 
        ### to extract the monodromy permutation
        ### recall that each entry of initial_sheets and final_sheets
        ### is of the form [i, x] with i the integer label
        ### and x the actual position of the sheet in the fiber 
        ### above the basepoint.
        sorted_sheets = []
        for s_1 in initial_sheets:
            closest_candidate = final_sheets[0]
            min_d = abs(s_1[1] - closest_candidate[1])
            for s_2 in final_sheets:
                if abs(s_2[1] - s_1[1]) < min_d:
                    min_d = abs(s_2[1] - s_1[1])
                    closest_candidate = s_2
            sorted_sheets.append(closest_candidate)
        
        ### Now we check that sheet tracking is not making a mistake.
        ### NOTE: cannot use the function 'delete_duplicates' with this 
        ### data structure.
        seen = set()
        uniq = []
        for s in sorted_sheets:
            if s[1] not in seen:
                uniq.append(s[1])
                seen.add(s[1])
        if len(uniq) < len(sorted_sheets):
            # When studying D-type covers there may be situations
            # where two sheets collide at x=0 everywhere
            # Do not raise an error in this case.
            if (
                self.g_data.type=='D' 
                and min(map(abs, [s[1] for s in sorted_sheets])) < self.accuracy
                and len(sorted_sheets)-len(uniq)==1
                ):
                # If two sheets are equal (and both zero) then the integer
                # labels they got assigned in sorting above may be the same,
                # this would lead to a singular permutation matrix
                # and must be corrected, as follows.
                int_labels = [s[0] for s in sorted_sheets]
                uniq_labels = list(set(int_labels))
                labels_multiplicities = [
                            len([i for i, x in enumerate(int_labels) if x == u]) 
                            for u in uniq_labels
                            ]
                multiple_labels = []
                for i, u in enumerate(uniq_labels):
                    if labels_multiplicities[i] > 1:
                        if labels_multiplicities[i] == 2:
                            multiple_labels.append(u)
                        else:
                            logging.info('int labels = {}'.format(int_labels))
                            logging.info('multiple labels = {}'.format(
                                        multiple_labels)
                                    )
                            raise Exception('Too many degenerate sheets')
                if len(multiple_labels)!=1:
                    raise Exception('Cannot determine which sheets are'+
                                    'degenerate, tracking will fail.')

                missing_label = [i for i in range(len(int_labels)) if 
                                    (i not in int_labels)][0]
                double_sheets = [i for i, s in enumerate(sorted_sheets) 
                                    if s[0]==multiple_labels[0]]

                corrected_sheets = sorted_sheets 
                corrected_sheets[double_sheets[0]] = (
                                            initial_sheets[double_sheets[0]]
                                        )
                corrected_sheets[double_sheets[1]] = (
                                            initial_sheets[double_sheets[1]]
                                        )
                sorted_sheets = corrected_sheets
                pass
            else:
                raise ValueError(
                    '\nError in determination of monodromy!\n' +
                    'Cannot match uniquely the initial sheets' + 
                    ' to the final ones.'
                    )
        else:
            pass

        ### Now we have tree lists:
        ### initial_sheets = [[0, x_0], [1, x_1], ...]
        ### final_sheets = [[0, x'_0], [1, x'_1], ...]
        ### sorted_sheets = [[i_0, x_0], [i_1, x_1], ...]
        ### therefore the monodromy permutation corresponds
        ### to 0 -> i_0, 1 -> i_1, etc.

        n_sheets = len(initial_sheets)

        logging.debug('Sorted sheets around locus {}'.format(sorted_sheets))
        
        ### NOTE: in the following basis vectors, i = 0 , ... , n-1
        def basis_e(i):
            return numpy.array([kr_delta(j, i) for j in range(n_sheets)])

        perm_list = []
        for i in range(n_sheets):
            new_sheet_index = sorted_sheets[i][0]
            perm_list.append(basis_e(new_sheet_index))

        perm_matrix = numpy.array(perm_list).transpose()

        logging.debug('Permutation matrix {}'.format(perm_matrix))

        return perm_matrix


    def analyze_branch_point(self, bp):
        logging.info(
            "Analyzing a branch point at z = {}."
            .format(bp.z)
        )
        path_to_bp = get_path_to(bp.z, self)
        sheets_along_path = self.get_sheets_along_path(
            path_to_bp, is_path_to_bp=True
        )
        xs_at_bp = [s_i[-1] for s_i in sheets_along_path]
        enum_sh = [[i, x_i] for i, x_i in enumerate(xs_at_bp)]
        
        clusters = []
        for i, x in enum_sh:
            is_single = True
            for c_index, c in enumerate(clusters):
                x_belongs_to_c = belongs_to_cluster(x, c, enum_sh)
                if x_belongs_to_c == True:
                    clusters[c_index].append(i)
                    is_single = False
                    break
            if is_single == True:
                clusters.append([i])

        bp.enum_sh = enum_sh
        bp.groups = [c for c in clusters if len(c) > 1]
        bp.singles = [c[0] for c in clusters if len(c) == 1]

        bp.positive_roots = get_positive_roots_of_branch_point(
            bp, self.g_data,  
        )
        bp.order = len(bp.positive_roots) + 1

        path_around_bp = get_path_around(bp.z, self.base_point, self)
        bp.monodromy = self.get_sheet_monodromy(path_around_bp)

        bp.ffr_ramification_points = [rp 
                    for rp in self.ffr_ramification_points
                    if abs(rp.z - bp.z) < self.accuracy]


    def analyze_irregular_singularity(self, irr_sing):
        logging.info(
            "Analyzing an irregular singularity at z = {}."
            .format(irr_sing.z)
        )
        path_around_z = get_path_around(irr_sing.z, self.base_point, self)
        irr_sing.monodromy = (
            self.get_sheet_monodromy(path_around_z)
        )
    
    def analyze_ffr_ramification_point(self, rp):
        rp_type = None
        num_eq = self.ffr_curve.num_eq

        # use Dz = z - rp.z & Dx = x - rp.x
        Dz, Dx = sympy.symbols('Dz, Dx')
        local_curve = (
            num_eq.subs(x, rp.x+Dx).subs(z, rp.z+Dz)
            .series(Dx, 0, rp.i+1).removeO()
            .series(Dz, 0, 2).removeO()
        )
        logging.debug('\nlocal curve = {}\n'.format(local_curve))
            
        # Classify which type of ramification point
        # type_I: ADE type with x_0 != 0
        #   #   i.e. F ~ a z + b x^k
        # type_II: D-type with x_0 = 0, but nonedgenerate
        #   i.e. F ~ a z + b x^2r   with r=rank(g)
        # type_III: D-type with x_0 = 0, degenerate
        #   i.e. F ~ x^2 (a z + b x^(2r-2))
        # type IV: Other case.
        # More cases may be added in the future, in particular 
        # for degenerations of E_6 or E_7 curves.

        zero_threshold = self.accuracy * 100
        if (self.g_data.type=='A' or 
            ((self.g_data.type=='D' or self.g_data.type=='E') and 
                abs(rp.x) > zero_threshold)):
            rp_type = 'type_I'
        elif (self.g_data.type=='D' and abs(rp.x) < zero_threshold
            and 2*self.g_data.rank==rp.i
            and abs(local_curve.n().subs(Dx, 0).coeff(Dz)) > zero_threshold):
            rp_type = 'type_II'
        elif (self.g_data.type=='D' and 2*self.g_data.rank==rp.i
            and abs(local_curve.n().subs(Dx, 0).coeff(Dz)) < zero_threshold):
            rp_type = 'type_III'
        else:
            rp_type = 'type_IV'
            raise Exception(
                    'Cannot handle this type of ramification point'.format(
                    local_curve)
                )

        if rp_type == 'type_I' or rp_type == 'type_II':
            a = local_curve.n().subs(Dx, 0).coeff(Dz)
            b = local_curve.n().subs(Dz, 0).coeff(Dx**rp.i)

        elif rp_type == 'type_III':
            a = local_curve.n().coeff(Dz).coeff(Dx, 2)
            b = local_curve.n().subs(Dz, 0).coeff(Dx**rp.i)
        
        logging.debug('\nThe ramification point at (z,x)={} is of {}'.format(
                        [rp.z, rp.x], rp_type)
                    )
        rp.ramification_type = rp_type

        num_v = self.diff.num_v
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

        # rp.sw_diff_coeff = complex(-1 * a / b)
        rp.sw_diff_coeff = complex(diff_c.n())





def get_path_to(z_pt, sw_data):
    """
    Return a rectangular path from the base point to z_pt.
    If the path has to pass too close to a branch point, 
    we avoid the latter by drawing an arc around it.
    """
    base_pt = sw_data.base_point
    closest_bp = None
    # if n_loci==None:
    #     n_loci = len(sw_data.branch_points + sw_data.irregular_singularities)
    # radius = sw_data.min_distance / n_loci
    radius = sw_data.min_horizontal_distance / 2.0

    logging.debug("Constructing a path [{}, {}]".format(base_pt, z_pt))

    ### Determine if the path will need to pass 
    ### close to a branch point.
    for bp in sw_data.branch_points:
        delta_z = z_pt - bp.z
        # NOTE we only check for one possible nearby point
        # based on the fact that the radius is always less
        # than the minimal horizontal separation of them
        if abs(delta_z.real) < radius and delta_z.imag > 0:
            closest_bp = bp
            break

    # If there the path does not pass near a branch point:
    if closest_bp == None:
        z_0 = base_pt
        z_1 = 1j * base_pt.imag + z_pt.real
        z_2 = z_pt
        half_steps = int(N_PATH_TO_PT / 2)
        return (
            [z_0 + ((z_1 - z_0) / half_steps) * i 
             for i in range(half_steps + 1)] + 
            [z_1 + ((z_2 - z_1) / half_steps) * i 
             for i in range(half_steps + 1)]                
        )

    # If there the path needs to pass near a branch point:
    else:
        z_0 = base_pt
        z_1 = 1j * base_pt.imag + closest_bp.z.real
        z_2 = 1j * (closest_bp.z.imag - radius) + closest_bp.z.real
        z_3 = closest_bp.z + radius * exp(1j * phase(z_pt - closest_bp.z))
        z_4 = z_pt
        
        if (z_pt - closest_bp.z).real > 0:
            ### way_around = 'ccw'
            sign = 1.0
            delta_theta = phase(z_pt - closest_bp.z) + pi / 2
        else:
            ### way_around = 'cw'
            sign = -1.0
            delta_theta = 3 * pi / 2 - phase(z_pt - closest_bp.z) 

        steps = int(N_PATH_TO_PT / 5)

        path_segment_1 = [z_0 + ((z_1 - z_0) / steps) * i
                          for i in range(steps + 1)]
        path_segment_2 = [z_1 + ((z_2 - z_1) / steps) * i 
                          for i in range(steps + 1)]
        path_segment_3 = [closest_bp.z + radius * (-1j) * 
                                exp(sign * 1j * (delta_theta) 
                                    * (float(i) / float(steps))
                                    ) 
                          for i in range(steps +1)]
        path_segment_4 = [z_3 + ((z_4 - z_3) / steps) * i
                          for i in range(steps + 1)]
        
        return (path_segment_1 + path_segment_2 
                + path_segment_3 + path_segment_4)
    


def get_path_around(z_pt, base_pt, sw):
    logging.debug("Constructing a closed path around z = {}".format(z_pt))
    z_0 = base_pt
    z_1 = 1j * base_pt.imag + z_pt.real
    # if n_loci==None:
    #     n_loci = len(sw.branch_points + sw.irregular_singularities)
    # radius = min_distance / n_loci
    radius = sw.min_horizontal_distance / 2.0
    z_2 = z_pt - 1j * radius

    steps = N_PATH_AROUND_PT
    path_segment_1 = [z_0 + ((z_1 - z_0) / steps) * i
                      for i in range(steps + 1)]
    path_segment_2 = [z_1 + ((z_2 - z_1) / steps) * i 
                      for i in range(steps + 1)]
    path_segment_3 = [z_pt + radius * (-1j) * exp(i * 2.0 * pi * 1j
                                                  / steps) 
                      for i in range(steps +1)]
    path_segment_4 = path_segment_2[::-1]
    path_segment_5 = path_segment_1[::-1]
    return (path_segment_1 + path_segment_2 + path_segment_3 +
            path_segment_4 + path_segment_5)


### TODO: Try using numba.
### TODO: Make smarter checks based on the types
### of ramification points above the branch point.
def get_sorted_xs(ref_xs, new_xs, accuracy=None, check_tracking=True, 
                  index=None, z_0=None, z_1=None, g_data=None,):
    """
    Returns a sorted version of 'new_xs'
    based on matching the closest points with 
    'ref_xs'
    """
    sorted_xs = []
    for s_1 in ref_xs:
        # closest_candidate = new_xs[0]
        # min_d = abs(s_1 - closest_candidate)
        # for s_2 in new_xs:
        #     if abs(s_2 - s_1) < min_d:
        #         min_d = abs(s_2 - s_1)
        #         closest_candidate = s_2
        closest_candidate = nsmallest(1, new_xs, key=lambda x: abs(x-s_1))[0]
        sorted_xs.append(closest_candidate)
        # rel_min_d = abs((s_1 - closest_candidate) / (s_1 + closest_candidate))
        # for s_2 in new_xs:
        #     if abs((s_2 - s_1)/max(map(abs, [s_2 , s_1]))) < rel_min_d:
        #         min_d = abs((s_2 - s_1)/max(map(abs, [s_2 , s_1])))
        #         closest_candidate = s_2
        # sorted_xs.append(closest_candidate)
    
    if check_tracking == True:
        ### Now we check that sheet tracking is not making a mistake.
        unique_sorted_xs = n_remove_duplicate(sorted_xs, accuracy)
        if len(unique_sorted_xs) < len(sorted_xs):
            # When studying D-type covers there may be situations
            # where two sheets collide at x=0 everywhere
            # Do not raise an error in this case.
            if (g_data.type=='D' and min(map(abs, sorted_xs)) < accuracy
                and len(sorted_xs)-len(unique_sorted_xs)==1):
                return sorted_xs
            else:
                logging.debug(
                        "At step %s, between %s and %s " % (index, z_0, z_1)
                    )
                logging.debug("ref_xs:\n{}".format(ref_xs)) 
                logging.debug("new_xs:\n{}".format(new_xs)) 
                logging.debug("sorted_xs:\n{}".format(sorted_xs)) 
                logging.debug("unique_sorted_xs:\n{}".format(unique_sorted_xs)) 
                logging.debug('Having trouble tracking sheets, will zoom in.')
                return 'sorting failed'
        else:
            return sorted_xs
    else:
        ### If the path is one ending on a branch-point, 
        ### the check that tracking is correct is disabled
        ### because it would produce an error, since by definition
        ### sheets will be indistinguishable at the very end.
        return sorted_xs

def sort_xs_by_derivative(ref_xs, new_xs, delta_xs, accuracy):
    # will only work if there are at most two sheets being 
    # too close two each other, not three or more.
    # TODO: generalize to handle more gneral cases (if we need it at all)
    logging.debug('Resorting to tracking sheets by their derivatives')
    groups = []
    # first, identify the problematic sheets
    ys = []
    for s_1 in ref_xs:
        closest_candidate = nsmallest(1, new_xs, key=lambda x: abs(x-s_1))[0]
        ys.append(closest_candidate)
        
    # the list of ys corresponds to the ref_xs as
    # ref_xs = [x_1, x_2, x_3, ...]
    #     ys = [y_1, y_2, y_1, ...]
    # and will contain doubles. 
    # We use them to identify the pairs that give trouble
    correct_xy_pairs = {}   # (a dictionary)
    trouble_xs = []
    trouble_ys = []
    for i in range(len(ys)):
        if ys.count(ys[i]) == 1:
            # add this key and value to the dictioanry
            correct_xy_pairs.update({ref_xs[i] : ys[i]})
        else:
            trouble_ys.append(ys[i])
    trouble_ys = n_remove_duplicate(trouble_ys, 0.0)
    for y_t in trouble_ys:
        # get all positions of the troubling y
        y_positions = [j for j, y in enumerate(ys) if y==y_t]
        # then get all x's which are mapped to it
        trouble_xs.append([ref_xs[j] for j in y_positions])

    for x_pair in trouble_xs:
        if len(x_pair) != 2:
            raise Exception('Cannot handle this kind of sheet degeneracy')
        else:
            closest_ys_0 = nsmallest(2, new_xs, key=lambda x: abs(x-x_pair[0]))
            closest_ys_1 = nsmallest(2, new_xs, key=lambda x: abs(x-x_pair[1]))
            # a check
            if (closest_ys_0!=closest_ys_1 
                and closest_ys_0!=closest_ys_1.reverse()):
                raise Exception(('the cloasest sheets to the reference pair {}'
                        '\ndont match: they are respectively:\n{}\n{}'
                        ).format(x_pair, closest_ys_0, closest_ys_1)
                    )
            else:
                # compute the differences of the various combinations
                dx_00 = closest_ys_0[0] - x_pair[0]
                dx_01 = closest_ys_0[1] - x_pair[0]
                dx_10 = closest_ys_0[0] - x_pair[1]
                dx_11 = closest_ys_0[1] - x_pair[1]
                # pick for each x in the x_pair its companion based on 
                # the phase of the displacement, choosing the closest to 
                # the previous step in the tracking
                i_0 = ref_xs.index(x_pair[0])
                i_1 = ref_xs.index(x_pair[1])
                ref_dx_0 = delta_xs[i_0]
                ref_dx_1 = delta_xs[i_1]
                # first find the companion for x_pair[0]
                if abs(phase(dx_00/ref_dx_0)) < abs(phase(dx_01/ref_dx_0)):
                    correct_xy_pairs.update({x_pair[0] : closest_ys_0[0]})
                else:
                    correct_xy_pairs.update({x_pair[0] : closest_ys_0[1]})
                # then repeat for x_pair[1]
                if abs(phase(dx_10/ref_dx_1)) < abs(phase(dx_11/ref_dx_1)):
                    correct_xy_pairs.update({x_pair[1] : closest_ys_0[0]})
                else:
                    correct_xy_pairs.update({x_pair[1] : closest_ys_0[1]})

    # at this point, we should have sorted all the new_xs
    # we check if the sorting was successful
    sorted_xs = [correct_xy_pairs[x] for x in ref_xs]
    unique_sorted_xs = n_remove_duplicate(sorted_xs, 0.0)

    if len(sorted_xs)==len(unique_sorted_xs):
        return sorted_xs
    else:
        return 'sorting failed'


def kr_delta(i, j):
    if i == j:
        return 1
    else:
        return 0


def get_positive_roots_of_branch_point(bp, g_data):
    """
    Determines the positive roots associated with 
    a branch point's 'structure', i.e. how the sheets
    collide at the branch point.
    It will return a minimal list, i.e. it will drop
    any redundant roots that can be obtained as linear
    combinations of others.
    """
    vanishing_positive_roots = []
    positive_roots = g_data.positive_roots
    ### Note that bp.groups carries indicies, which can be used
    ### to map each x at the reference point to the weights, i.e.
    ### reference_xs[i] <-> weights[i].
    weights = g_data.weights


    for g in bp.groups:
        ### Within each group of colliding sheets/weights,
        ### consider all possible pairs, and compute 
        ### the corresponding difference.
        ### Then add it to the vanishing positive roots.
        for s_1, s_2 in combinations(g, 2):
            v_1 = weights[s_1]
            v_2 = weights[s_2]
            if any(numpy.allclose(v_1 - v_2, x) for x in positive_roots):
                vanishing_positive_roots.append(v_1 - v_2)

            elif any(numpy.allclose(v_2 - v_1, x) for x in positive_roots):
                vanishing_positive_roots.append(v_2 - v_1)

            else:
                continue
    if vanishing_positive_roots == []:
        logging.info("Branch point doesn't correspond "
                "to a positive root. May be an accidental branch point.")
        return []

    ### Finally, cleanup the duplicates, 
    ### as well as the roots which are not linearly independent
    ### TODO: Check if we really need to remove linearly depedent 
    ### roots. Isn't it part of the information a branch pt carries?
    ### Pietro: the information of the branch point is the vector space
    ### spanned by these roots. Therefore only linearly independent ones 
    ### are needed.
    return keep_linearly_independent_vectors(vanishing_positive_roots)

def belongs_to_cluster(x, c, enum_sh):
    """
    Given a cluster of sheets, c = [i_0, i_1, ...]
    specified by means of their integer labels,
    it determines whether a sheet with coordinate 'x'
    is close enough to ANY of the sheets in 'c'
    to be considered as part of it.
    The positions of sheets in the cluster are extracted
    from enum_sh = [...[i_k, x_k]...]
    """
    test = False
    for i in c:
        ### pick the coordinate of the sheet with label 'i'
        y_i = [y for j, y in enum_sh if j==i][0]
        if abs(y_i - x) < BP_PROXIMITY_THRESHOLD:
            test = True
            break

    if test == False:
        return False
    if test == True:
        return True


def keep_linearly_independent_vectors(vector_list):
    """
    Takes a list of numpy arrays and returns a 
    subset of linearly independent ones.
    """
    
    first_vector = vector_list[0]
    independent_list = [first_vector]

    m_rank = 1
    m = numpy.matrix([first_vector])
    for v in vector_list:
        ### add the vector as a row to the matrix, 
        ### then compute the rank
        new_m = numpy.vstack([m,v])
        new_m_rank = matrix_rank(new_m)
        if new_m_rank > m_rank:
            m = new_m
            m_rank = new_m_rank
            independent_list.append(v)

    return independent_list


