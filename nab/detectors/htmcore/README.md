# HtmcoreDetector HTM implementation from [htm.core](https://github.com/htm-community/htm.core/)

This detector provides HTM implementation from [htm.core](https://github.com/htm-community/htm.core/),
which is an actively developed, community version of Numenta's [nupic.core](https://github.com/numenta/nupic.core). 

This is a python 3 detector, called `htmcore`, as Numenta is switching NAB to python 3, this is the closes detector you can get to 
`numenta`, `numentaTM` detectors. 

`Htm.core` offers API and features similar and compatible with the official HTM implementations `nupic`, `nupic.core`. Although there
are significant speed and features improvements available! For more details please see [the htm.core project's README](https://github.com/htm-community/htm.core/blob/master/README.md)
Bugs and questions should also be reported there. 

## Installation

`htmcore` detector is automatically installed with your `NAB` installation (`python setup.py install`),
so you don't have to do anything to have it available. 

### Requirements to install

- [Python 3](https://www.python.org/download/)
- [htm.core](https://github.com/htm-community/htm.core)
    - You can either build it yourself from source, 
    - Install from [binary releases](https://github.com/htm-community/htm.core/releases)
    - Or easiest, `python -m pip install --extra-index-url https://test.pypi.org/simple/ htm.core`

## Usage

Is the same as the default detectors, see [NAB README section Usage](https://github.com/htm-community/NAB/blob/master/README.md#usage)

### Example
Follow the instructions in the main README to run optimization, scoring, and normalization, e.g.:

`python run.py -d htmcore --optimize --score --normalize`

