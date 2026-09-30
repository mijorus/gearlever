Grab the test files here:

https://github.com/mijorus/gearlever-test-files

Offline update-check regression tests (requires the Python/GTK dependencies
used by Gear Lever; does not install, remove, or update AppImages):

```sh
python3 -m unittest discover -s tests -p test_update_errors.py -v
```
