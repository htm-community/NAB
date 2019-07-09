#!/bin/bash

# This is a helper script to install python2 detectors (numenta, htmjava) if possible.
# It is done through creating a python2 virtualenv and installing the packages there. 

[ ! -x "`which virtualenv`" ] && echo "Virtualenv required!" && exit
[ ! -x "`which python2`" ] && echo "Python 2 not installed, skipping installation of python2-only detectors (numenta, numentaTM, htmjava)" && exit
REPO=`pwd`

echo $REPO
virtualenv --python=python2 ${REPO}/pyenv2
source ${REPO}/pyenv2/bin/activate

ls $REPO

python --version

## Install Python 2 detectors:

# 1/ Numenta detector
pip install nupic --force
python nab/detectors/numenta/setup.py develop 

pip list

deactivate
