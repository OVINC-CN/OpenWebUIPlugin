export PACKAGE_PATH=`python -c "import site; print(site.getsitepackages()[0])"`

ln -s "$PACKAGE_PATH/ovinc_client" ovinc_client

python manage.py makemessages -l zh_Hans --no-wrap --no-location -s

rm ovinc_client
