## [HTM Java](https://github.com/numenta/htm.java) NAB detector

### Run [htm.java](https://github.com/numenta/htm.java) with NAB on your local machine

First make sure you have __java 8__ installed

    java -version

## Installation

### Java

#### Requirements
- Java 8
- gradle (on Windows you can use bundled gradlew.bat)

First make sure you have __java 8__ installed. You should see a version number matching 1.8.XXXX.

```
$ java -version
java version "1.8.0_211"
Java(TM) SE Runtime Environment (build 1.8.0_211-b12)
Java HotSpot(TM) 64-Bit Server VM (build 25.211-b12, mixed mode)
```

Navigate to the *inner* `htmjava` directory and build __htm.java__ NAB detector:
    
```
cd nab/detectors/htmjava
gradle clean build
```

Once this has built correctly navigate back to the *outer* `htmjava` directory
and continue with the Python installation and usage described below.

`cd ../../../`

### Python

We assume you have a working version of Python 3 installed as your default Python.
If your default system Python is still Python 2 you can skip the virtual environment
creation below.

#### Requirements to install

- [Python 2.7](https://www.python.org/download/)
- [Virtualenv](https://pypi.org/project/virtualenv/)

#### Install a virtual environment

Create a new Python 2 virtual environment in this directory.

`virtualenv -p path/to/python2 env`

Activate that virtual environment.

`./env/Scripts/activate`

or

`env\Scripts\activate.bat` on Windows.

Confirm you have a local Python 2

```
$ python
Python 2.7.13 (v2.7.13:a06454b1afa1, Dec 17 2016, 20:53:40) [MSC v.1500 64 bit (AMD64)] on win32
Type "help", "copyright", "credits" or "license" for more information.
>>>
```

#### Install NuPIC

Run __htm.java__ NAB detector:
    
    cd /path/to/nab
    python run.py -d htmjava --detect --optimize --score --normalize

This will run the `detect` phase of NAB on the data files specified in the above
JSON file. Note that scoring and normalization are not supported with this
option. Note also that you may see warning messages regarding the lack of labels
for other files. You can ignore these warnings.
