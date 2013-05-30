from setuptools import setup, find_packages

setup(
    name= "auth_bot",
    version = "0.0.1",
    packages = ['snoonet'],
    install_requires = ['twisted', 'requests'],
    author = "t0mcat",
    author_email = "diminoten@snoonet.org",
    url = "https://github.com/t0mcat/auth_bot",
    entry_points = {
            'console_scripts':[
                'auth_bot = snoonet.auth:start_auth_bot'
            ]
    }
)
