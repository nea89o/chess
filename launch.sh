#!/bin/bash
git pull
pipenv install --deploy

pipenv run python server.py



