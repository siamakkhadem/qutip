#This file is part of QuTIP.
#
#    QuTIP is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#    QuTIP is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with QuTIP.  If not, see <http://www.gnu.org/licenses/>.
#
# Copyright (C) 2011, Paul D. Nation & Robert J. Johansson
#
###########################################################################

##
# @mainpage QuTiP: Quantum Toolbox in Python
#
#QuTiP is open-source software for simulating the dynamcis of 
#open quantum systems.  The QuTiP library depends on the 
#excellent Numpy and Scipy numerical packages. In addition, 
#graphical output is provided by Matplotlib.  QuTiP aims
#to provide user-friendly and efficient numerical simulations
#of a wide variety of Hamiltonian's, including those with 
#arbitrary time-dependent, commonly found in a wide range of 
#physics applications. QuTiP is freely avaliable for use and/or 
#modification on all major platforms. Being free of any licensing 
#fees, QuTiP is ideal for exploring quantum mechanics and 
#dynamics in the classroom.
#
#
#
# These pages contains automatically generated API documentation.
#

import os,sys,multiprocessing

#automatically set number of threads used by MKL
os.environ['MKL_NUM_THREADS']=str(multiprocessing.cpu_count())

#
# default, use graphics (unless QUTIP_GRPAHICS is already set)
#
if not os.environ.has_key('QUTIP_GRAPHICS'):
    os.environ['QUTIP_GRAPHICS']="YES"

#check if being run remotely
if not os.environ.has_key('DISPLAY'):
    #no graphics if DISPLAY isn't set
    os.environ['QUTIP_GRAPHICS']="NO"
    os.environ['QUTIP_GUI']="NONE"

#-Check for Matplotlib
try:
    import matplotlib
except:
    os.environ['QUTIP_GRAPHICS']="NO"
    os.environ['QUTIP_GUI']="NONE"


#if being run locally, check for installed gui modules
if os.environ['QUTIP_GRAPHICS']=="YES":
    try:
        import PySide
        os.environ['QUTIP_GUI']="PYSIDE"
    except:
        try:
            import PyQt4
            os.environ['QUTIP_GUI']="PYQT4"
        except:
            os.environ['QUTIP_GRAPHICS']="NO"
            os.environ['QUTIP_GUI']="NONE"
#----------------------------------------------------
from scipy import *
import scipy.linalg as la
import scipy.sparse as sp
from Qobj import Qobj,shape,dims,dag,trans,sp_expm
from about import *
from Bloch import Bloch
from graph import hinton
from correlation import *
from clebsch import clebsch
from eseries import *
from demos import *
from entropy import *
import examples
from expect import *
from gates import *
from istests import *
from Odeoptions import Odeoptions
from mcsolve import mcsolve
from metrics import fidelity,tracedist
from odesolve import odesolve
from essolve import *
from operators import *
from orbital import *
from parfor import *
from ptrace import ptrace
from propagator import *
from qstate import *
from sphereplot import *
from states import *
from steady import *
from superoperator import *
from tensor import *
from wigner import *


