#!/bin/bash

# This is a helper script to install python2 detectors (numenta, htmjava) if possible.
# It is done through creating a python2 virtualenv and installing the packages there.
# Requirements: virtualenv, pytnon2, bash
# If fails, nothing happens, but py2 detectors won't be usable

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
python nab/detectors/numenta/setup.py install --force 

# 2/ htmjava detector

[ ! -x "`which gradle`" ] && echo "htmjava detector requires gradle to build" && exit
[ ! -x "`which java`" ] && "htmjava requires java! :) Preferably Java 8" && exit

cd ./nab/detectors/htmjava/nab/detectors/htmjava #inception, I know :P 
gradle clean build || exit
cd ${REPO}
python nab/detectors/htmjava/setup.py install --force

echo "Installation of Py2 detectors finished:"
pip list | grep nab
