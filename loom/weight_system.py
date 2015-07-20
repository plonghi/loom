import subprocess
import ast

def weight_system(algebra, highest_weight):
    """
    Arguments must be formatted as follows:
    algebra = 'D3'
    highest_weight = [0, 1, 1]
    """
    out = subprocess.check_output(
        ["sage", "./sage_scripts/weight_system.sage", 
         algebra, 
         str(highest_weight)
        ]
    )
    weights, multiplicities = eval(eval(out))
    return weights, multiplicities

