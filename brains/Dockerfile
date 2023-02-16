# syntax=docker/dockerfile:1
FROM python:3

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

CMD [ "python", "./tb.py", "--config", "./trolbrains.conf" ]

