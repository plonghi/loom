"""
Main module. Run 'python -m loom' at the directory that contains the
directory 'loom'.

This module is based on the following libraries:
NumPy 1.8.2
SciPy 0.15.1
SymPy 0.7.6 -> must be installed
"""
import sys
import logging
import os
import getopt
import time

from config import LoomConfig
from gui import open_gui
from spectral_network import load_spectral_network, generate_spectral_network

shortopts = 'c:gl:p:'
longopts = [
    'gui-mode',
    'logging-level',
    'phase',
    'show-plot',
    'load-data=',
    'save-data=',
]

CONFIG_FILE_DIR = 'config_file'
DATA_FILE_DIR = 'data_file'


def run_with_optlist(optlist):

    opts = {
        'config-file': None,
        'gui-mode': False,
        'logging-level': 'warning',
        'phase': None,
        #'single-network': False,
        'load-data': '',
        'show-plot': False,
    }
        
    if len(optlist) == 0:
        print("""usage: python -m loom [OPTION]

    -c CFG_FILE_NAME:
        Read CFG_FILE_NAME to set up the configuration.

    -g, --gui-mode:
        Run the graphical user interface.

    -l LEVEL, --logging-level=LEVEL:
        Set logging level to LEVEL. 'warning' is default.

    -p, --phase THETA:
        Generate a spectral network at the phase of THETA.
        Overrides 'phase_range' of the configuration file. 

    --load-data DATA_FILE:
        load data from a file.
        
    --show-plot:
        diaplay the spectral network plot.
        """)

    else:

        for opt, arg in optlist:
            if (opt == '-c' and len(arg) > 0):
                opts['config-file'] = arg
            elif (opt == '-g' or opt == '--gui-mode'):
                opts['gui-mode'] = True
            elif (opt == '-l' or opt == '--logging-level'):
                opts['logging-level'] = arg
            elif (opt == '-p' or opt == '--phase'):
                opts['phase'] = float(arg)
                #opts['single-network'] = True
            elif opt == '--load-data':
                opts['load-data'] = arg
            elif opt == '--show-plot':
                opts['show-plot'] = True
        # End of option setting.

        # Set logging.
        if opts['logging-level'] == 'debug':
            logging_level = logging.DEBUG
            logging_format = '%(module)s@%(lineno)d: %(funcName)s: %(message)s'
        elif opts['logging-level'] == 'info':
            logging_level = logging.INFO
            logging_format = '%(process)d: %(message)s'
        else:
            logging_level = logging.WARNING
            logging_format = '%(message)s'

        logging.basicConfig(level=logging_level, format=logging_format, 
                            stream=sys.stdout)

        config = LoomConfig()
        # Entry point branching
        if opts['gui-mode'] is True:
            return open_gui(opts, config)
        elif (len(opts['load-data']) > 0):
            data_dir = opts['load-data']
            config.read(os.path.join(data_dir, 'config.ini'))
            return load_spectral_network(data_dir, config)
        else:
            if opts['config-file'] is None:
                config_file = os.path.join(CONFIG_FILE_DIR, 'default.ini')
            else:
                config_file = opts['config-file']
            config.read(config_file)
            return generate_spectral_network(opts, config)

# Set options from sys.argv when running on the command line,
# then start running the main code.
def run_with_sys_argv(argv):    
    try:
        optlist, args = getopt.getopt(argv, shortopts, longopts,)
        return run_with_optlist(optlist)

    except getopt.GetoptError:
        print 'Unknown options.'

# Set options from string 'optstr' when running on the interpreter, 
# then start running the main code.
def run(optstr=''):
    return run_with_sys_argv(optstr.split())

# End of definitions

if __name__ == '__main__':
    run_with_sys_argv(sys.argv[1:])
