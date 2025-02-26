pylint:
	scripts/pylint.sh

pre-commit:
	scripts/pre-commit.sh

lint: pre-commit pylint

requirements:
	scripts/requirements.sh

init:
	pip install -r requirements.txt && pip install -r requirements_dev.txt

