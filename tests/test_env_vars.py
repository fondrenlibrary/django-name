import os


def test_env_vars():
    DB_HOST = os.getenv('DB_HOST', default='DB_HOST is not set')
    DB_PASSWORD = os.getenv('DB_PASSWORD', default='DB_PASSWORD is not set')
    DB_USER = os.getenv('DB_USER', default='DB_USER is not set')

    print '\n'
    print 'DB_HOST is set to: {0}'.format(DB_HOST)
    print 'DB_PASSWORD is set to: {0}'.format(DB_PASSWORD)
    print 'DB_USER is set to: {0}'.format(DB_USER)
    print '\n'
