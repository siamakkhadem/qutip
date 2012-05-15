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
#Copyright (C) 2011-2012, Paul D. Nation & Robert J. Johansson
#
###########################################################################

import sys,os,time,numpy,datetime
from scipy import *
from scipy.integrate import *
from scipy.linalg import norm
from qutip.Qobj import *
from qutip.expect import *
from qutip.istests import *
from qutip.Odeoptions import Odeoptions
import qutip.odeconfig as odeconfig
from multiprocessing import Pool,cpu_count
from types import FunctionType
from qutip.cyQ.cy_mc_funcs import mc_expect,spmv,cy_mc_no_time
from qutip.cyQ.ode_rhs import cyq_ode_rhs
from qutip.cyQ.codegen import Codegen
from qutip.rhs_generate import rhs_generate
from Odedata import Odedata
from odechecks import _ode_checks
import qutip.settings
from _reset import _reset_odeconfig

def mcsolve(H,psi0,tlist,c_ops,e_ops,ntraj=500,args={},options=Odeoptions()):
    """Monte-Carlo evolution of a state vector :math:`|\psi \\rangle` for a given
    Hamiltonian and sets of collapse operators and operators
    for calculating expectation values. Options for solver are 
    given by the Odeoptions class.
    
    Parameters
    ----------
    H : qobj
        System Hamiltonian.
    psi0 : qobj 
        Initial state vector
    tlist : array_like 
        Times at which results are recorded.
    ntraj : int 
        Number of trajectories to run.
    c_ops : array_like 
        ``list`` or ``array`` of collapse operators.
    e_ops : array_like 
        ``list`` or ``array`` of operators for calculating expectation values.
    args : dict
        Arguments for time-dependent Hamiltonian and collapse operator terms.
    options : Odeoptions
        Instance of ODE solver options.
    
    Returns
    -------
    results : Odedata    
        Object storing all results from simulation.
        
    """
    #reset odeconfig collapse and time-dependence flags to default values
    _reset_odeconfig()
    
    #check for type of time-dependence (if any)
    time_type,h_stuff,c_stuff=_ode_checks(H,c_ops,'mc')
    h_terms=len(h_stuff[0])+len(h_stuff[1])+len(h_stuff[2])
    c_terms=len(c_stuff[0])+len(c_stuff[1])+len(c_stuff[2])
    #set time_type for use in multiprocessing
    odeconfig.tflag=time_type
    #check for collapse operators
    if c_terms>0:
        odeconfig.cflag=1
    else:
        odeconfig.cflag=0
    
    #Configure data
    _mc_data_config(H,psi0,h_stuff,c_ops,c_stuff,args,e_ops,options)
    
    #load monte-carlo class
    mc=MC_class(psi0,tlist,ntraj,c_ops,e_ops,options)
    #RUN THE SIMULATION
    mc.run()
    
    
    #AFTER MCSOLVER IS DONE --------------------------------------
    #if (odeconfig.tflag in array([1,10,11,12])) and (not options.rhs_reuse):
        #try:
            #os.remove(odeconfig.tdname+".pyx")
        #except:
            #print("Error removing pyx file.  File not found.")
    
    #-------COLLECT AND RETURN OUTPUT DATA IN ODEDATA OBJECT --------------#
    output=Odedata()
    output.states=mc.psi_out
    if any(mc.expect_out) and odeconfig.cflag and options.mc_avg==True:#averaging if multiple trajectories
        output.expect=mean(mc.expect_out,axis=0)
    else:#no averaging for single trajectory or if mc_avg flag (Odeoptions) is off
        output.expect=mc.expect_out

    output.times=mc.times
    output.num_expect=odeconfig.e_num
    output.num_collapse=odeconfig.c_num
    output.ntraj=mc.ntraj
    output.collapse_times=mc.collapse_times_out
    output.collapse_which=mc.which_op_out
    return output


#--------------------------------------------------------------
# MONTE-CARLO CLASS                                           #
#--------------------------------------------------------------
class MC_class():
    """
    Private class for solving Monte-Carlo evolution from mcsolve
    
    """
    def __init__(self,psi0,tlist,ntraj,c_ops,e_ops,options):
        
        #----CLASS SETUP-------------------------------#
        
        ##ODE options from Odeoptions class
        self.options=options
        #-Check for PyObjC on Mac platforms
        if sys.platform=='darwin':
            try:
                import Foundation
            except:
                self.options.gui=False
        #check if running in iPython and using Cython compiling (then no GUI to work around error)
        if self.options.gui and odeconfig.tflag==1:
            try:
                __IPYTHON__
            except:
                pass
            else:
                self.options.gui=False    
        if qutip.settings.qutip_gui=="NONE":self.options.gui=False
        #set num_cpus to the value given in qutip.settings if none in Odeoptions
        if not self.options.num_cpus:
            self.options.num_cpus=qutip.settings.num_cpus
        #----------------------------------------------#
        
        
        #----MAIN OBJECT PROPERTIES--------------------#
        ##holds instance of the ProgressBar class
        self.bar=None
        ##holds instance of the Pthread class
        self.thread=None
        ##check if user wants multiple trajectory averages
        if isinstance(ntraj,(list,ndarray)):
            ntraj=sum(ntraj)
        ##number of Monte-Carlo trajectories
        self.ntraj=ntraj
        #Number of completed trajectories
        self.count=0
        ##step-size for count attribute
        self.step=1
        ##Percent of trajectories completed
        self.percent=0.0
        ##used in implimenting the command line progress ouput
        self.level=0.1
        ##times at which to output state vectors or expectation values
        self.times=tlist
        ##number of time steps in tlist
        self.num_times=len(tlist)
        #holds seed for random number generator
        self.seed=None
        #holds expected time to completion
        self.st=None
        #number of cpus to be used 
        self.cpus=options.num_cpus
        
        #set output variables, even if they are not used to simplify output code.
        self.psi_out=None
        self.expect_out=None
        self.collapse_times_out=None
        self.which_op_out=None
        
        #FOR EVOLUTION FOR NO COLLAPSE OPERATORS---------------------------------------------
        if odeconfig.c_num==0:
            if odeconfig.e_num==0:
                ##Output array of state vectors calculated at times in tlist
                self.psi_out=array([Qobj()]*self.num_times)#preallocate array of Qobjs
            elif odeconfig.e_num!=0:#no collpase expectation values
                ##List of output expectation values calculated at times in tlist
                self.expect_out=[]
                for i in xrange(odeconfig.e_num):
                    if self.e_ops_isherm[i]:#preallocate real array of zeros
                        self.expect_out.append(zeros(self.num_times))
                    else:#preallocate complex array of zeros
                        self.expect_out.append(zeros(self.num_times,dtype=complex))
                    self.expect_out[i][0]=mc_expect(self.e_ops_data[i],self.e_ops_ind[i],self.e_ops_ptr[i],self.e_ops_isherm[i],self.psi_in)
        
        #FOR EVOLUTION WITH COLLAPSE OPERATORS---------------------------------------------
        elif odeconfig.c_num!=0:
            #preallocate #ntraj arrays for state vectors, collapse times, and which operator
            self.collapse_times_out=zeros((self.ntraj),dtype=ndarray)
            self.which_op_out=zeros((self.ntraj),dtype=ndarray)
            if odeconfig.e_num==0:# if no expectation operators, preallocate #ntraj arrays for state vectors
                self.psi_out=array([zeros((self.num_times),dtype=object) for q in xrange(self.ntraj)])#preallocate array of Qobjs
            else: #preallocate array of lists for expectation values
                self.expect_out=[[] for x in xrange(self.ntraj)]
    #-------------------------------------------------#
    
    
    #---CLASS METHODS---------------------------------#
    def callback(self,results):
        r=results[0]
        if odeconfig.e_num==0:#output state-vector
            self.psi_out[r]=results[1]
        else:#output expectation values
            self.expect_out[r]=results[1]
        self.collapse_times_out[r]=results[2]
        self.which_op_out[r]=results[3]
        self.count+=self.step
        if (not self.options.gui): #do not use GUI
            self.percent=self.count/(1.0*self.ntraj)
            if self.count/float(self.ntraj)>=self.level:
                #calls function to determine simulation time remaining
                self.level=_time_remaining(self.st,self.ntraj,self.count,self.level)
    #-----
    def parallel(self,args,top=None):  
        self.st=datetime.datetime.now() #set simulation starting time
        pl=Pool(processes=self.cpus)
        [pl.apply_async(mc_alg_evolve,args=(nt,args),callback=top.callback) for nt in xrange(0,self.ntraj)]
        pl.close()
        try:
            pl.join()
        except KeyboardInterrupt:
            print "Cancel all MC threads on keyboard interrupt"
            pl.terminate()
            pl.join()
        return
    #-----
    def run(self):
        if odeconfig.tflag in array([1,10,11]): #compile time-depdendent RHS code
            if not self.options.rhs_reuse:
                print "Compiling '"+odeconfig.tdname+".pyx' ..."
                os.environ['CFLAGS'] = '-w'
                import pyximport
                pyximport.install(setup_args={'include_dirs':[numpy.get_include()]})
                if odeconfig.tflag in array([1,11]):
                    code = compile('from '+odeconfig.tdname+' import cyq_td_ode_rhs,col_spmv,col_expect', '<string>', 'exec')
                    exec(code)
                    odeconfig.tdfunc=cyq_td_ode_rhs
                    odeconfig.colspmv=col_spmv
                    odeconfig.colexpect=col_expect
                else:
                    code = compile('from '+odeconfig.tdname+' import cyq_td_ode_rhs', '<string>', 'exec')
                    exec(code)
                    odeconfig.tdfunc=cyq_td_ode_rhs
        if odeconfig.c_num==0:
            if self.ntraj!=1:#check if ntraj!=1 which is pointless for no collapse operators
                self.ntraj=1
                print('No collapse operators specified.\nRunning a single trajectory only.\n')
            if odeconfig.e_num==0:# return psi Qobj at each requested time 
                self.psi_out=no_collapse_psi_out(self.options,odeconfig.psi0,self.times,self.num_times,odeconfig.psi0_dims,odeconfig.psi0_shape,self.psi_out)
            else:# return expectation values of requested operators
                self.expect_out=no_collapse_expect_out(self.options,odeconfig.psi0,self.times,odeconfig.e_ops_data,odeconfig.e_ops_ind,odeconfig.e_ops_ptr,odeconfig.e_ops_isherm,self.num_times,odeconfig.psi0_dims,odeconfig.psi0_shape,self.expect_out)
        elif odeconfig.c_num!=0:
            self.seed=array([int(ceil(random.rand()*1e4)) for ll in xrange(self.ntraj)])
            if odeconfig.e_num==0:
                mc_alg_out=zeros((self.num_times),dtype=ndarray)
                mc_alg_out[0]=odeconfig.psi0
            else:
                #PRE-GENERATE LIST OF EXPECTATION VALUES
                mc_alg_out=[]
                for i in xrange(odeconfig.e_num):
                    if odeconfig.e_ops_isherm[i]:#preallocate real array of zeros
                        mc_alg_out.append(zeros(self.num_times))
                    else:#preallocate complex array of zeros
                        mc_alg_out.append(zeros(self.num_times,dtype=complex))
                    mc_alg_out[i][0]=mc_expect(odeconfig.e_ops_data[i],odeconfig.e_ops_ind[i],odeconfig.e_ops_ptr[i],odeconfig.e_ops_isherm[i],odeconfig.psi0)
            
            #set arguments for input to monte-carlo
            args=(mc_alg_out,self.options,self.times,self.num_times,self.seed)
            if not self.options.gui:
                self.parallel(args,self)
            else:
                if qutip.settings.qutip_gui=="PYSIDE":
                    from PySide import QtGui,QtCore
                elif qutip.settings.qutip_gui=="PYQT4":
                    from PyQt4 import QtGui,QtCore
                from gui.ProgressBar import ProgressBar,Pthread
                app=QtGui.QApplication.instance()#checks if QApplication already exists (needed for iPython)
                if not app:#create QApplication if it doesnt exist
                    app = QtGui.QApplication(sys.argv)
                thread=Pthread(target=self.parallel,args=args,top=self)
                self.bar=ProgressBar(self,thread,self.ntraj,self.cpus)
                QtCore.QTimer.singleShot(0,self.bar.run)
                self.bar.show()
                self.bar.activateWindow()
                self.bar.raise_()
                app.exec_()
                return
                


#----------------------------------------------------
#
# CODES FOR PYTHON BASED TIME-DEPENDENT HAMILTONIANS
#
#----------------------------------------------------

#RHS of ODE for time-dependent systems with no collapse operators
def RHStd(t,psi):
    return odeconfig.Hfunc(t,odeconfig.Hargs)*psi

#RHS of ODE for time-dependent systems with collapse operators
def cRHStd(t,psi):
    return (odeconfig.Hfunc(t,odeconfig.Hargs)+odeconfig.Hcoll)*psi





######---return psi at requested times for no collapse operators---######
def no_collapse_psi_out(opt,psi_in,tlist,num_times,psi_dims,psi_shape,psi_out):
    ##Calculates state vectors at times tlist if no collapse AND no expectation values are given.
    #
    if odeconfig.tflag==1:
        ODE=ode(odeconfig.tdfunc)
        code = compile('ODE.set_f_params('+odeconfig.string+')', '<string>', 'exec')
        exec(code)
    elif odeconfig.tflag==2:
        ODE=ode(RHStd)
    else:
        #ODE=ode(RHS)
        ODE = ode(cyq_ode_rhs)
        ODE.set_f_params(odeconfig.Hdata, odeconfig.Hinds, odeconfig.Hptrs)
        
    ODE.set_integrator('zvode',method=opt.method,order=opt.order,atol=opt.atol,rtol=opt.rtol,nsteps=opt.nsteps,first_step=opt.first_step,min_step=opt.min_step,max_step=opt.max_step) #initialize ODE solver for RHS
    ODE.set_initial_value(psi_in,tlist[0]) #set initial conditions
    psi_out[0]=Qobj(psi_in,dims=psi_dims,shape=psi_shape)
    for k in xrange(1,num_times):
        ODE.integrate(tlist[k],step=0) #integrate up to tlist[k]
        if ODE.successful():
            psi_out[k]=Qobj(ODE.y/norm(ODE.y,2),dims=psi_dims,shape=psi_shape)
        else:
            raise ValueError('Error in ODE solver')
    return psi_out
#------------------------------------------------------------------------


######---return expectation values at requested times for no collapse operators---######
def no_collapse_expect_out(opt,psi_in,tlist,e_ops_data,e_ops_ind,e_ops_ptr,e_ops_isherm,num_times,psi_dims,psi_shape,expect_out):
    ##Calculates xpect.values at times tlist if no collapse ops. given
    #  
    #------------------------------------
    num_expect=len(e_ops_data)
    if odeconfig.tflag==1:
        ODE=ode(odeconfig.tdfunc)
        code = compile('ODE.set_f_params('+odeconfig.string+')', '<string>', 'exec')
        exec(code)
    elif odeconfig.tflag==2:
        ODE=ode(RHStd)
    else:
        ODE = ode(cyq_ode_rhs)
        ODE.set_f_params(odeconfig.Hdata, odeconfig.Hinds, odeconfig.Hptrs)
    ODE.set_integrator('zvode',method=opt.method,order=opt.order,atol=opt.atol,rtol=opt.rtol,nsteps=opt.nsteps,first_step=opt.first_step,min_step=opt.min_step,max_step=opt.max_step) #initialize ODE solver for RHS
    ODE.set_initial_value(psi_in,tlist[0]) #set initial conditions
    for jj in xrange(num_expect):
        expect_out[jj][0]=mc_expect(e_ops_data[jj],e_ops_ind[jj],e_ops_ptr[jj],e_ops_isherm[jj],psi_in)
    for k in xrange(1,num_times):
        ODE.integrate(tlist[k],step=0) #integrate up to tlist[k]
        if ODE.successful():
            state=ODE.y/norm(ODE.y)
            for jj in xrange(num_expect):
                expect_out[jj][k]=mc_expect(e_ops_data[jj],e_ops_ind[jj],e_ops_ptr[jj],e_ops_isherm[jj],state)
        else:
            raise ValueError('Error in ODE solver')
    return expect_out #return times and expectiation values
#------------------------------------------------------------------------


#---single-trajectory for monte-carlo---          
def mc_alg_evolve(nt,args):
    """
    Monte-Carlo algorithm returning state-vector or expectation values at times tlist for a single trajectory.
    """
    #get input data
    mc_alg_out,opt,tlist,num_times,seeds=args

    #number of operators of each type
    num_expect=odeconfig.e_num
    num_collapse=odeconfig.c_num
    
    collapse_times=[] #times at which collapse occurs
    which_oper=[] # which operator did the collapse
    
    #SEED AND RNG AND GENERATE
    random.seed(seeds[nt])
    rand_vals=random.rand(2)#first rand is collapse norm, second is which operator
    
    #CREATE ODE OBJECT CORRESPONDING TO RHS
    if odeconfig.tflag in array([1,10,11]):
        ODE=ode(odeconfig.tdfunc)
        code = compile('ODE.set_f_params('+odeconfig.string+')', '<string>', 'exec')
        exec(code)
    #elif odeconfig.tflag==2:
        #ODE=ode(RHStd)
    else:
        ODE = ode(cyq_ode_rhs)
        ODE.set_f_params(odeconfig.Hdata, odeconfig.Hinds, odeconfig.Hptrs)
    
    ODE.set_integrator('zvode',method=opt.method,order=opt.order,atol=opt.atol,rtol=opt.rtol,nsteps=opt.nsteps,
                        first_step=opt.first_step,min_step=opt.min_step,max_step=opt.max_step) #initialize ODE solver for RHS
    ODE.set_initial_value(odeconfig.psi0,tlist[0]) #set initial conditions
    #RUN ODE UNTIL EACH TIME IN TLIST
    cinds=arange(num_collapse)
    for k in xrange(1,num_times):
        #ODE WHILE LOOP FOR INTEGRATE UP TO TIME TLIST[k]
        while ODE.successful() and ODE.t<tlist[k]:
            last_t=ODE.t;last_y=ODE.y
            ODE.integrate(tlist[k],step=1) #integrate up to tlist[k], one step at a time.
            psi_nrm2=norm(ODE.y,2)**2
            if psi_nrm2<=rand_vals[0]:# <== collpase has occured
                collapse_times.append(ODE.t)
                #some string based collapse operators
                if odeconfig.tflag in array([1,11]):
                    n_dp=[mc_expect(odeconfig.n_ops_data[i],odeconfig.n_ops_ind[i],odeconfig.n_ops_ptr[i],1,ODE.y) for i in odeconfig.c_const_inds]
                    exec(odeconfig.col_expect_code)
                    n_dp=array(n_dp)
                #all constant collapse operators.
                else:
                    n_dp=array([mc_expect(odeconfig.n_ops_data[i],odeconfig.n_ops_ind[i],odeconfig.n_ops_ptr[i],1,ODE.y) for i in xrange(num_collapse)])
                kk=cumsum(n_dp/sum(n_dp))
                j=cinds[kk>=rand_vals[1]][0]
                which_oper.append(j) #record which operator did collapse
                if j in odeconfig.c_const_inds:
                    state=spmv(odeconfig.c_ops_data[j],odeconfig.c_ops_ind[j],odeconfig.c_ops_ptr[j],ODE.y)
                else:
                    exec(odeconfig.col_spmv_code)
                state_nrm=norm(state,2)
                ODE.set_initial_value(state/state_nrm,ODE.t)
                rand_vals=random.rand(2)
        #-------------------------------------------------------
        ###--after while loop--####
        psi=copy(ODE.y)
        if ODE.t>last_t:
            psi=(psi-last_y)/(ODE.t-last_t)*(tlist[k]-last_t)+last_y
        epsi=psi/norm(psi,2)
        if num_expect==0:
            mc_alg_out[k]=epsi
        else:
            for jj in xrange(num_expect):
                mc_alg_out[jj][k]=mc_expect(odeconfig.e_ops_data[jj],odeconfig.e_ops_ind[jj],odeconfig.e_ops_ptr[jj],odeconfig.e_ops_isherm[jj],epsi)
    #RETURN VALUES
    if num_expect==0:
        mc_alg_out=array([Qobj(k,odeconfig.psi0_dims,odeconfig.psi0_shape,'ket') for k in mc_alg_out])
        return nt,mc_alg_out,array(collapse_times),array(which_oper)
    else:
        return nt,mc_alg_out,array(collapse_times),array(which_oper)
#------------------------------------------------------------------------------------------




def _time_remaining(st,ntraj,count,level):
    """
    Private function that determines, and prints, how much simulation time is remaining.
    """
    nwt=datetime.datetime.now()
    diff=((nwt.day-st.day)*86400+(nwt.hour-st.hour)*(60**2)+(nwt.minute-st.minute)*60+(nwt.second-st.second))*(ntraj-count)/(1.0*count)
    secs=datetime.timedelta(seconds=ceil(diff))
    dd = datetime.datetime(1,1,1) + secs
    time_string="%02d:%02d:%02d:%02d" % (dd.day-1,dd.hour,dd.minute,dd.second)
    print str(floor(count/float(ntraj)*100))+'%  ('+str(count)+'/'+str(ntraj)+')'+'  Est. time remaining: '+time_string
    level+=0.1
    return level


def _mc_data_config(H,psi0,h_stuff,c_ops,c_stuff,args,e_ops,options):
    """Creates the appropriate data structures for the monte carlo solver
    based on the given time-dependent, or indepdendent, format.
    """
    #set initial value data
    if options.tidy:
        odeconfig.psi0=psi0.tidyup(options.atol).full()
    else:
        odeconfig.psi0=psi0.full()
    odeconfig.psi0_dims=psi0.dims
    odeconfig.psi0_shape=psi0.shape
    #----
    #take care of expectation values, if any
    if any(e_ops):
        odeconfig.e_num=len(e_ops)
        odeconfig.e_ops_data=array([op.data.data for op in e_ops])
        odeconfig.e_ops_ind=array([op.data.indices for op in e_ops])
        odeconfig.e_ops_ptr=array([op.data.indptr for op in e_ops])
        odeconfig.e_ops_isherm=array([op.isherm for op in e_ops])
    #----
    
    #take care of collapse operators, if any
    if any(c_ops):
        odeconfig.c_num=len(c_ops)
        for c_op in c_ops:
            if isinstance(c_op,list):
                c_op=c_op[0]
            n_op=c_op.dag()*c_op
            odeconfig.c_ops_data.append(c_op.data.data)
            odeconfig.c_ops_ind.append(c_op.data.indices)
            odeconfig.c_ops_ptr.append(c_op.data.indptr)
            #norm ops
            odeconfig.n_ops_data.append(n_op.data.data)
            odeconfig.n_ops_ind.append(n_op.data.indices)
            odeconfig.n_ops_ptr.append(n_op.data.indptr)
        #to array
        odeconfig.c_ops_data=array(odeconfig.c_ops_data)
        odeconfig.c_ops_ind=array(odeconfig.c_ops_ind)
        odeconfig.c_ops_ptr=array(odeconfig.c_ops_ptr)
        odeconfig.n_ops_data=array(odeconfig.n_ops_data)
        odeconfig.n_ops_ind=array(odeconfig.n_ops_ind)
        odeconfig.n_ops_ptr=array(odeconfig.n_ops_ptr)
    #----
    
    
    #Hamiltonian & collapse terms are time-INDEPENDENT
    if odeconfig.tflag==0:
        if odeconfig.cflag:
            odeconfig.c_const_inds=arange(len(c_ops))
            for c_op in c_ops:
                n_op=c_op.dag()*c_op
                H -= 0.5j * n_op #combine Hamiltonian and collapse terms into one
        #construct Hamiltonian data structures
        if options.tidy:
            H=H.tidyup(options.atol)
        odeconfig.Hdata=-1.0j*H.data.data
        odeconfig.Hinds=H.data.indices
        odeconfig.Hptrs=H.data.indptr  
    #----
    
    #Hamiltonian &/or collapse terms have string-type time-DEPENDENCE
    elif odeconfig.tflag in array([1,10,11]):
        #take care of arguments for collapse operators, if any
        if any(args):
            arg_items=args.items()
            for k in xrange(len(args)):
                odeconfig.c_args.append(arg_items[k][1])
        #constant Hamiltonian / string-type collapse operators
        if odeconfig.tflag==1:
            H_inds=arange(1)
            H_tdterms=0
            len_h=1
            C_inds=arange(odeconfig.c_num)
            C_td_inds=array(c_stuff[2]) #find inds of time-dependent terms
            C_const_inds=setdiff1d(C_inds,C_td_inds) #find inds of constant terms
            C_tdterms=[c_ops[k][1] for k in C_td_inds] #extract time-dependent coefficients (strings)
            odeconfig.c_const_inds=C_const_inds#store indicies of constant collapse terms
            odeconfig.c_td_inds=C_td_inds#store indicies of time-dependent collapse terms
            
            for k in odeconfig.c_const_inds:
                H-=0.5j*(c_ops[k].dag()*c_ops[k])
            if options.tidy:
                H=H.tidyup(options.atol)
            odeconfig.Hdata=[H.data.data]
            odeconfig.Hinds=[H.data.indices]
            odeconfig.Hptrs=[H.data.indptr]
            for k in odeconfig.c_td_inds:
                op=c_ops[k][0].dag()*c_ops[k][0]
                odeconfig.Hdata.append(-0.5j*op.data.data)
                odeconfig.Hinds.append(op.data.indices)
                odeconfig.Hptrs.append(op.data.indptr)
            odeconfig.Hdata=-1.0j*array(odeconfig.Hdata)
            odeconfig.Hinds=array(odeconfig.Hinds)
            odeconfig.Hptrs=array(odeconfig.Hptrs)
        
        #string-type Hamiltonian & string-type (or constant) collapse operators
        else:
            H_inds=arange(len(H))
            H_td_inds=array(h_stuff[2]) #find inds of time-dependent terms
            H_const_inds=setdiff1d(H_inds,H_td_inds) #find inds of constant terms
            H_tdterms=[H[k][1] for k in H_td_inds] #extract time-dependent coefficients (strings or functions)
            H=array([sum(H[k] for k in H_const_inds)]+[H[k][0] for k in H_td_inds]) #combine time-INDEPENDENT terms into one.
            len_h=len(H)
            H_inds=arange(len_h)
            odeconfig.h_td_inds=arange(1,len_h)#store indicies of time-dependent Hamiltonian terms
            #if there are any collpase operatorss
            if odeconfig.c_num>0:
                if odeconfig.tflag==10: #constant collapse operators
                    odeconfig.c_const_inds=arange(odeconfig.c_num)
                    for k in odeconfig.c_const_inds:
                        H[0]-=0.5j*(c_ops[k].dag()*c_ops[k])
                    C_inds=arange(odeconfig.c_num)
                    C_tdterms=array([])
                #-----
                else:#some time-dependent collapse terms
                    C_inds=arange(odeconfig.c_num)
                    C_td_inds=array(c_stuff[2]) #find inds of time-dependent terms
                    C_const_inds=setdiff1d(C_inds,C_td_inds) #find inds of constant terms
                    C_tdterms=[c_ops[k][1] for k in C_td_inds] #extract time-dependent coefficients (strings)
                    odeconfig.c_const_inds=C_const_inds#store indicies of constant collapse terms
                    odeconfig.c_td_inds=C_td_inds#store indicies of time-dependent collapse terms
            
            else:#set empty objects if no collapse operators
                C_const_inds=arange(odeconfig.c_num)
                odeconfig.c_const_inds=range(odeconfig.c_num)
                odeconfig.c_td_inds=array([])
                C_tdterms=array([])
                C_inds=array([])
            
            
            #tidyup
            if options.tidy:
                H=array([H[k].tidyup(options.atol) for k in xrange(len_h)])
            #construct data sets
            odeconfig.Hdata=[H[k].data.data for k in xrange(len_h)]
            odeconfig.Hinds=[H[k].data.indices for k in xrange(len_h)]
            odeconfig.Hptrs=[H[k].data.indptr for k in xrange(len_h)]
            for k in odeconfig.c_td_inds:
                odeconfig.Hdata.append(-0.5j*odeconfig.n_ops_data[k])
                odeconfig.Hinds.append(odeconfig.n_ops_ind[k])
                odeconfig.Hptrs.append(odeconfig.n_ops_ptr[k])
            odeconfig.Hdata=-1.0j*array(odeconfig.Hdata)
            odeconfig.Hinds=array(odeconfig.Hinds)
            odeconfig.Hptrs=array(odeconfig.Hptrs)
        #----
        
        #set execuatble code for collapse expectation values and spmv
        col_spmv_code="state=odeconfig.colspmv(j,ODE.t,odeconfig.c_ops_data[j],odeconfig.c_ops_ind[j],odeconfig.c_ops_ptr[j],ODE.y"
        col_expect_code="n_dp+=[odeconfig.colexpect(i,ODE.t,odeconfig.n_ops_data[i],odeconfig.n_ops_ind[i],odeconfig.n_ops_ptr[i],ODE.y"
        for kk in xrange(len(odeconfig.c_args)):
            col_spmv_code+=",odeconfig.c_args["+str(k)+"]"
            col_expect_code+=",odeconfig.c_args["+str(k)+"]"
        col_spmv_code+=")"
        col_expect_code+=") for i in odeconfig.c_td_inds]"
        odeconfig.col_spmv_code=compile(col_spmv_code,'<string>', 'exec')
        odeconfig.col_expect_code=compile(col_expect_code,'<string>', 'exec')    
        #----
        
        
        #setup ode args string
        odeconfig.string=""
        data_range=range(len(odeconfig.Hdata))
        for k in data_range:
            odeconfig.string+="odeconfig.Hdata["+str(k)+"],odeconfig.Hinds["+str(k)+"],odeconfig.Hptrs["+str(k)+"]"
            if k!=data_range[-1]:
                odeconfig.string+="," 
        #attach args
        if any(args):
            td_consts=args.items()
            for elem in td_consts:
                odeconfig.string+=","+str(elem[1])
        #----
        if not options.rhs_reuse:
            name="rhs"+str(odeconfig.cgen_num)
            odeconfig.tdname=name
            cgen=Codegen(H_inds,H_tdterms,odeconfig.h_td_inds,args,C_inds,C_tdterms,odeconfig.c_td_inds)
            cgen.generate(name+".pyx")
        #----
        
    #--------------------------------------------
    # NON-CYTHON TIME-DEPENDENT CODE
    elif isinstance(H,FunctionType):
        odeconfig.tflag=2
        odeconfig.Hfunc=H
        odeconfig.Hargs=-1.0j*array([op.data for op in args])
        if len(c_ops)>0:
            odeconfig.cflag=1
            Hq=0
            for c_op in c_ops:
                Hq -= 0.5j * (c_op.dag()*c_op)
            Hq=Hq.tidyup(options.atol)
            odeconfig.Hcoll=-1.0j*Hq.data



