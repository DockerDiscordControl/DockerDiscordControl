Quick Start Guide
=================

This guide will help you get started with DDC API development quickly.

Installation
------------

1. **Clone the repository**:

   .. code-block:: bash

      git clone https://github.com/DockerDiscordControl/DockerDiscordControl.git
      cd DockerDiscordControl

2. **Install dependencies**:

   .. code-block:: bash

      pip install -r requirements.txt

3. **Configure DDC**:

   .. code-block:: bash

      # Copy example config
      cp config/config.example.json config/config.json

      # Edit with your settings
      nano config/config.json

Basic Usage
-----------

Load Configuration
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from services.config.config_service import get_config_service

   # Get singleton service instance
   config_service = get_config_service()

   # Load configuration
   config = config_service.get_config()

   print(f"Language: {config['language']}")
   print(f"Servers: {len(config['servers'])} containers")

Work with Containers
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Get container list
   servers = config['servers']

   for server in servers:
       name = server['container_name']
       actions = server['allowed_actions']
       print(f"{name}: {', '.join(actions)}")

Encrypt Tokens
~~~~~~~~~~~~~~

.. code-block:: python

   from werkzeug.security import generate_password_hash

   # Generate password hash
   password_hash = generate_password_hash("my-password")

   # Encrypt token
   encrypted = config_service.encrypt_token(
       plaintext_token="MTIzNDU2.ABC.xyz",
       password_hash=password_hash
   )

Next Steps
----------

* Read the :doc:`services/index` for complete API reference
* Check :doc:`examples` for more code samples
* See :doc:`ERROR_HANDLING` for exception handling
