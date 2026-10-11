Installation
============

Install from PyPI using pip:

.. code-block:: bash

   pip install dmxtty

The only dependency is `pyserial <https://pyserial.readthedocs.io/>`_.
Python 3.11 or newer is required.

Serial Port Permissions
-----------------------

Opening a serial port normally requires membership in the ``dialout`` group:

.. code-block:: bash

   sudo usermod -aG dialout $USER

Log out and back in for the change to take effect.

Building the Documentation
--------------------------

.. code-block:: bash

   pip install -e ".[docs]"
   sphinx-build -W --keep-going -b html docs docs/_build/html
