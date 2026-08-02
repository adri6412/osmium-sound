# Makes `python -m unittest discover -s tests -t .` work from the repo root, so
# the test modules can import the daemons (api_server, hifi_backup, ...) the same
# way they are imported on the appliance.
