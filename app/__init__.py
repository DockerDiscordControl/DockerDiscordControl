from flask import Flask

def create_app(config_name='default'):
    app = Flask(__name__)
    return app
