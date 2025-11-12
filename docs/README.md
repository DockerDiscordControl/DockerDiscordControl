# DockerDiscordControl API Documentation

This directory contains the complete API documentation for DockerDiscordControl, generated using Sphinx.

## Documentation Structure

```
docs/
├── source/              # Sphinx source files (RST format)
│   ├── index.rst       # Main documentation index
│   ├── examples.rst    # Usage examples
│   ├── services/       # Service API documentation
│   │   ├── index.rst
│   │   └── config_services.rst
│   ├── api/            # Auto-generated API docs
│   ├── _static/        # Static files (CSS, images)
│   └── _templates/     # Custom Sphinx templates
├── build/              # Generated HTML documentation
│   └── html/          # HTML output
└── README.md           # This file
```

## Building the Documentation

### Prerequisites

Install Sphinx and required extensions:

```bash
pip install sphinx sphinx-rtd-theme
```

### Build HTML Documentation

```bash
cd docs
sphinx-build -b html source build/html
```

Or use the Makefile (if available):

```bash
cd docs
make html
```

### View Documentation

Open `build/html/index.html` in your browser:

```bash
# macOS
open build/html/index.html

# Linux
xdg-open build/html/index.html

# Windows
start build/html/index.html
```

## Documentation Sections

### 1. Introduction
- Project overview
- Key features
- Architecture overview

### 2. Quick Start
- Installation guide
- Basic usage examples
- Configuration setup

### 3. Services API
- **Configuration Services**: ConfigService, ConfigLoaderService, etc.
- **Docker Services**: Docker operations and async queue
- **Donation Services**: Ko-fi integration and power system
- **Mech Services**: Evolution system and animations
- **Web Services**: Flask web UI and authentication

### 4. API Reference
- Auto-generated API documentation from docstrings
- Complete method signatures
- Type hints and return values
- Exception handling

### 5. Usage Examples
- Real-world code examples
- Error handling patterns
- Testing examples
- Integration examples

### 6. Error Handling
- Custom exception hierarchy
- Recovery strategies
- Best practices

## Writing Documentation

### Docstring Format

Use Google-style docstrings for all public methods:

```python
def my_method(param1: str, param2: int = 0) -> Dict[str, Any]:
    """Short description of the method.

    Longer description explaining what the method does,
    how it works, and any important details.

    Args:
        param1 (str): Description of param1
        param2 (int, optional): Description of param2. Defaults to 0.

    Returns:
        Dict[str, Any]: Description of return value structure:

            * 'key1': Description of key1
            * 'key2': Description of key2

    Raises:
        ConfigServiceError: When configuration is invalid
        ValueError: When param1 is empty

    Example:
        >>> result = my_method("test", param2=5)
        >>> print(result['key1'])

    Note:
        Any important notes or warnings.

    See Also:
        :meth:`other_method` - Related method
        :class:`RelatedClass` - Related class
    """
    pass
```

### RST Formatting

Common RST directives:

```rst
.. code-block:: python

   # Python code example
   config = get_config_service().get_config()

.. note::

   Important information for the reader.

.. warning::

   Critical warning that users should be aware of.

.. autoclass:: services.config.config_service.ConfigService
   :members:
   :undoc-members:
   :show-inheritance:
```

## Documentation Coverage

Check documentation coverage:

```bash
cd docs
sphinx-build -b coverage source build/coverage
cat build/coverage/python.txt
```

## Continuous Documentation

### Auto-rebuild on Changes

Use sphinx-autobuild for live reload during development:

```bash
pip install sphinx-autobuild
cd docs
sphinx-autobuild source build/html
```

Then open http://127.0.0.1:8000 in your browser.

### Pre-commit Hook

Add a pre-commit hook to rebuild docs:

```bash
#!/bin/bash
# .git/hooks/pre-commit

cd docs
sphinx-build -b html source build/html -W
```

## API Documentation Standards

### Complete Documentation Requirements

All public classes and methods must have:

1. **Short description** (one line)
2. **Long description** (detailed explanation)
3. **Args section** (all parameters with types)
4. **Returns section** (return type and structure)
5. **Raises section** (all possible exceptions)
6. **Example section** (at least one usage example)
7. **See Also section** (related classes/methods)

### Documentation Checklist

- [ ] Class docstring with overview
- [ ] All public methods documented
- [ ] Type hints on all parameters
- [ ] Return types specified
- [ ] Exceptions documented
- [ ] Usage examples provided
- [ ] Related classes cross-referenced
- [ ] RST formatting validated
- [ ] Sphinx builds without warnings
- [ ] Coverage check passes

## Sphinx Configuration

The `source/conf.py` file contains:

- **Project information**: Name, version, author
- **Extensions**: autodoc, napoleon, viewcode, etc.
- **Theme**: ReadTheDocs theme
- **Autodoc settings**: Member ordering, type hints
- **Napoleon settings**: Google/NumPy docstring support

## Publishing Documentation

### GitHub Pages

To publish docs to GitHub Pages:

```bash
# Build docs
cd docs
sphinx-build -b html source build/html

# Copy to gh-pages branch
git checkout gh-pages
cp -r build/html/* .
git add .
git commit -m "Update documentation"
git push origin gh-pages
```

### Read the Docs

1. Connect repository to https://readthedocs.org
2. Configure build in `.readthedocs.yaml`
3. Documentation builds automatically on push

## Troubleshooting

### Build Errors

**"No module named 'services'"**

Add project root to Python path in `conf.py`:

```python
import sys
sys.path.insert(0, os.path.abspath('../..'))
```

**"WARNING: autodoc: failed to import"**

Check that all dependencies are installed:

```bash
pip install -r requirements.txt
```

**"Theme not found"**

Install the theme:

```bash
pip install sphinx-rtd-theme
```

### Missing Documentation

Run coverage check to find undocumented code:

```bash
sphinx-build -b coverage source build/coverage
cat build/coverage/python.txt | grep "UNDOC"
```

## Resources

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [ReadTheDocs Theme](https://sphinx-rtd-theme.readthedocs.io/)
- [Napoleon Extension](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html)
- [Google Style Docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)

## Contributing

When adding new services or features:

1. Write Google-style docstrings for all public APIs
2. Add usage examples to `source/examples.rst`
3. Create service-specific documentation in `source/services/`
4. Build and check for warnings: `sphinx-build -b html -W source build/html`
5. Verify examples work by running them
6. Update this README if adding new documentation sections

## License

Documentation is licensed under MIT License, same as the project.
