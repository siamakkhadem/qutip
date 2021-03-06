#
# Textbook example: Rabi oscillation in the dissipative Jaynes-Cummings model.
# 
#
from qutip import *
from pylab import *
import time

import warnings
warnings.simplefilter("error", np.ComplexWarning)


def qubit_integrate(epsilon, delta, g1, g2, solver):

    H = epsilon / 2.0 * sigmaz() + delta / 2.0 * sigmax()
        
    # collapse operators
    c_op_list = []

    rate = g1
    if rate > 0.0:
        c_op_list.append(sqrt(rate) * sigmam())

    rate = g2
    if rate > 0.0:
        c_op_list.append(sqrt(rate) * sigmaz())

    if solver == "ode":
        output = mesolve(H, psi0, tlist, c_op_list, [sigmax(), sigmay(), sigmaz()])  
    elif solver == "es":
        output = essolve(H, psi0, tlist, c_op_list, [sigmax(), sigmay(), sigmaz()])  
    elif solver == "mc":
        ntraj = 250
        output = mcsolve(H, psi0, tlist, ntraj, c_op_list, [sigmax(), sigmay(), sigmaz()])  
    else:
        raise ValueError("unknown solver")
        
    return output.expect[0], output.expect[1], output.expect[2]
    
#
# set up the calculation
#
epsilon = 0.0 * 2 * pi   # cavity frequency
delta   = 1.0 * 2 * pi   # atom frequency
g2 = 0.000
g1 = 0.0001

# intial state
psi0 = basis(2,0)

tlist = linspace(0,5,200)

# analytics
sx_analytic = zeros(shape(tlist))
sy_analytic = -sin(2*pi*tlist) * exp(-tlist * g2)
sz_analytic = cos(2*pi*tlist) * exp(-tlist * g2)

start_time = time.time()
sx1, sy1, sz1 = qubit_integrate(epsilon, delta, g1, g2, "ode")
print 'ME time elapsed = ' +str(time.time() - start_time) 

start_time = time.time()
sx2, sy2, sz2 = qubit_integrate(epsilon, delta, 0, 0, "ode")
print 'WF time elapsed = ' +str(time.time() - start_time) 


figure(1)
plot(tlist, real(sx1), 'r')
plot(tlist, real(sy1), 'b')
plot(tlist, real(sz1), 'g')
plot(tlist, sx_analytic, 'r*')
plot(tlist, sy_analytic, 'g*')
plot(tlist, sz_analytic, 'g*')
legend(("sx", "sy", "sz"))
xlabel('Time')
ylabel('expectation value')


figure(2)
plot(tlist, real(sx2), 'r')
plot(tlist, real(sy2), 'b')
plot(tlist, real(sz2), 'g')
plot(tlist, sx_analytic, 'r*')
plot(tlist, sy_analytic, 'g*')
plot(tlist, sz_analytic, 'g*')
legend(("sx", "sy", "sz"))
xlabel('Time')
ylabel('expectation value')

show()


#print "sx error =", max(abs(sx - sx_analytic))
#print "sy error =", max(abs(sy - sy_analytic))
#print "sy error =", max(abs(sz - sz_analytic))




