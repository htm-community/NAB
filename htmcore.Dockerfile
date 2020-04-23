FROM python:3.7

COPY . /NAB

WORKDIR /NAB

RUN pip install . --user --extra-index-url https://test.pypi.org/simple/

CMD python run.py -d htmcore --skipConfirmation --detect --optimize --score --normalize