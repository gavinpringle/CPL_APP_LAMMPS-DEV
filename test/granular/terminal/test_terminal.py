import os
import sys
import errno
import pytest
import subprocess as sp
import numpy as np
import time

# Add python scripts to path and import required classes
sys.path.append('../python_scripts/')
from LAMMPS_Input import LAMMPS_Input, LAMMPS_Writer
from MOCK_Input import MOCK_Input

# Run coupled simulation as subprocess
def run_coupled(run_bash_script='run.sh'):
    try:
        cmd = './' + run_bash_script
        p = sp.Popen(cmd, 
            stdout=sp.PIPE, 
            stderr=sp.STDOUT, 
            shell=True)
        while p.poll() is None:
            l = p.stdout.readline()
            print(l.rstrip())
        print(p.stdout.read())
    except:
        raise RuntimeError('Error running bash run script' + run_bash_script + ' in base directory.')
    p.wait()
    
# Extract the input parameters from DEM script for LAMMPS and OpenFOAM case
# directory. Check that they are consistent.
def get_input_parameters(md_input_file='./lammps/terminal.in', cfd_input_file='./CFD_dummy_terminal.py'):    
    mObj = LAMMPS_Input(md_input_file)
    cObj = MOCK_Input(cfd_input_file)

    # Calculate porosity and add to mObj
    Vc = ((cObj.xyzL[0]-cObj.xyz_orig[0])/cObj.ncxyz[0])*((cObj.xyzL[1]-cObj.xyz_orig[1])/cObj.ncxyz[1])*((cObj.xyzL[2]-cObj.xyz_orig[2])/cObj.ncxyz[2])
    mObj.epsf = (Vc - (np.pi/6)*(mObj.diameter**3))/Vc

    return mObj

# Set the input parameters for the simulations. At present, only the particle
# diameter and drag force model can be adjusted. Both these only apply to the
# LAMMPS input.
def set_input_parameters(dp, dragModel, md_input_file='./lammps/terminal.in'):
    LAMMPS_Writer(md_input_file, 'diameter', dp)
    LAMMPS_Writer(md_input_file, 'dragModel', dragModel)

# Calculate the analytical displacement and velocity profile of the particle,
# along with the terminal velocity. This is only applicable for the Stokes
# drag law, at present.
def analytical_velocity_displacement(t, mObj):
    
    rhof = mObj.fluid_density
    muf = mObj.dynamic_viscosity
    rhop = mObj.density
    dp = mObj.diameter
    g = -mObj.gravity
    y0 = mObj.y0
    vy0 = mObj.vy0
    epsf = mObj.epsf

    mp = rhop*(np.pi/6)*dp**3
    mf = rhof*(np.pi/6)*dp**3
    
    # Note that kd cannot have an epsf term, as Uf = 0. is hardwired into the
    # CFD dummy script.
    kd = 3*np.pi*muf*dp

    xySol = ((mp - mf)*g/kd)*(t - (mp/kd)*(1 - np.exp(-kd*t/mp))) + (vy0*mp/kd)*(1 - np.exp(-kd*t/mp)) + y0
    vySol = ((mp - mf)*g/kd)*(1 - np.exp(-kd*t/mp)) + vy0*np.exp(-kd*t/mp)
    vyTer = ((mp - mf)*g/kd)*np.ones_like(t)

    return xySol, vySol, vyTer

# Read print data for the top particle on column
def read_print_data(xy0, vy0, print_file='./lammps/print_terminal.txt'):
    # Try reading the print file. StopIteration error occurs with 'CPL_init
    # has been called more than once. Returning same COMM' error during
    # coupled run causing the print_file to exist but be empty (and hence the
    # skip_header error). Temporary work around is to re-run the coupled
    # simulation after waiting for 3 seconds. Only attempt this re-run three
    # times.
    for i in range(3):
        try:
            data = np.genfromtxt(print_file, skip_header=1)
            break
        except StopIteration:
            print("genfromtxt read error, waiting 3 secs and will try again")
            time.sleep(3)
            run_coupled()
    
    # Extract data
    t = data[:,0]
    xy = data[:,1]
    vy = data[:,2]

    # Append initial values
    t = np.insert(t, 0, 0)
    xy = np.insert(xy, 0, xy0)
    vy = np.insert(vy, 0, vy0)

    return t, xy, vy

# Plot displacement and velocity profile obtained from numerical simulation
# and analytical solution. Save the file in the results directory (which is
# created if required) and also save the data used for plotting as .npz file.
def plot_displacement_velocity(t, xy, xySol, vy, vySol, vyTer, file_name='./fig'):
    # Import matplotlib
    import matplotlib.pyplot as plt

    # Plot displacement
    plt.plot(t, xy, 'r-')
    plt.plot(t, xySol, 'k--')
    plt.xlabel('Time (s)')
    plt.ylabel('Position (cm)')
    plt.legend(('Numerical', 'Analytical'))
    plt.tight_layout()
    if not os.path.exists(os.path.dirname(file_name)):
        try:
            os.makedirs(os.path.dirname(file_name))
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
    plt.savefig(file_name + '_displacement.png')
    np.savez(file_name + '_displacement.npz', t=t, xy=xy, xySol=xySol)
    plt.close()
    
    # Plot velocity
    plt.plot(t, vy, 'r-')
    plt.plot(t, vySol, 'k--')
    plt.plot(t, vyTer, 'k:')
    plt.xlabel('Time (s)')
    plt.ylabel('Velocity (cm/s)')
    plt.legend(('Numerical', 'Analytical', 'Terminal'))
    plt.tight_layout()
    if not os.path.exists(os.path.dirname(file_name)):
        try:
            os.makedirs(os.path.dirname(file_name))
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
    plt.savefig(file_name + '_velocity.png')
    np.savez(file_name + '_velocity.npz', t=t, vy=vy, vySol=vySol, vyTer=vyTer)
    plt.close()

# Compare the displacement profile with time for a specified relative error.
def compare_displacement(t, xy, xySol, tol=0.01):
    for i in range(len(t)):
        err = abs((xySol[i] - xy[i])/xySol[i] <= tol)
        assert err, ('Displacement of {:.6f} does not match analytical'.format(xy[i])
                + ' solution of {:.6f} at time {:4f} within {:.2f}% relative error.'.format(xySol[i], t[i], tol*100))

# Compare the velocity profile with time for a specified relative error.
# Ignore the first five entries at t = 0, which is usually v = 0, as this
# would lead to division by zero with relative error analysis.
def compare_velocity(t, vy, vySol, tol=0.01):
    for i in range(len(t)):
        if i > 5:
            err = abs((vySol[i] - vy[i])/vySol[i] <= tol)
            assert err, ('Velocity of {:.6f} does not match analytical'.format(vy[i])
                    + ' solution of {:.6f} at time {:4f} within {:.2f}% relative error.'.format(vySol[i], t[i], tol*100))

# Compare the terminal velocity at the end of simulation for a specified
# relative error.
def compare_terminal(t, vy, vyTer, tol=0.01):
    err = abs((vyTer[-1] - vy[-1])/vyTer[-1]) <= tol
    assert err, ('Terminal velocity of {:.6f} does not match analytical'.format(vy[-1])
            + ' solution of {:.6f} within {:.2f}% relative error.'.format(vyTer[-1], tol*100))

# ----- Main ----- #
dragModels = ['Drag', 'Stokes']
dp_values = [0.01, 0.02, 0.03, 0.04, 0.05]
@pytest.mark.parametrize('dragModel', dragModels)
@pytest.mark.parametrize('dp', dp_values)
def test_displacement_velocity(dp, dragModel, plot_results=False):

    # Set input parameters
    set_input_parameters(dp, dragModel)
    
    # Run coupled simulation
    run_coupled()

    # Extract input parameters
    mObj = get_input_parameters()

    # Load print data
    t, xy, vy = read_print_data(mObj.y0, mObj.vy0)
    
    # Extract input parameters from lammps input script
    xySol, vySol, vyTer = analytical_velocity_displacement(t, mObj)

    # Plot the results
    if plot_results:
        plot_displacement_velocity(t, xy, xySol, vy, vySol, vyTer, 
            file_name='./results/fig_dp_{}_{}'.format(dp, dragModel))
    
    compare_displacement(t, xy, xySol, tol=0.02)
    compare_velocity(t, vy, vySol, tol=0.02)
    compare_terminal(t, vy, vyTer, tol=0.02)

if __name__ == "__main__":
    test_displacement_velocity(dp=0.05, dragModel='Stokes', plot_results=True)
