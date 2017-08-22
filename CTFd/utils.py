import base64
import datetime
import functools
import hashlib
import json
import logging
import logging.handlers
import mistune
import os
import re
import requests
import shutil
import six
import smtplib
import socket
import sys
import tempfile
import time
import dataset
import zipfile
import io

from email.mime.text import MIMEText
from flask import current_app as app, request, redirect, url_for, session, render_template, abort
from flask_caching import Cache
from flask_migrate import Migrate, upgrade as migrate_upgrade, stamp as migrate_stamp
from itsdangerous import TimedSerializer, BadTimeSignature, Signer, BadSignature
from six.moves.urllib.parse import urlparse, urljoin, quote, unquote
from werkzeug.utils import secure_filename

from CTFd.models import db, WrongKeys, Pages, Config, Tracking, Teams, Files, ip2long, long2ip

cache = Cache()
migrate = Migrate()
markdown = mistune.Markdown()


def init_logs(app):
    logger_keys = logging.getLogger('keys')
    logger_logins = logging.getLogger('logins')
    logger_regs = logging.getLogger('regs')

    logger_keys.setLevel(logging.INFO)
    logger_logins.setLevel(logging.INFO)
    logger_regs.setLevel(logging.INFO)

    try:
        parent = os.path.dirname(__file__)
    except:
        parent = os.path.dirname(os.path.realpath(sys.argv[0]))

    log_dir = os.path.join(parent, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logs = [
        os.path.join(parent, 'logs', 'keys.log'),
        os.path.join(parent, 'logs', 'logins.log'),
        os.path.join(parent, 'logs', 'registers.log')
    ]

    for log in logs:
        if not os.path.exists(log):
            open(log, 'a').close()

    key_log = logging.handlers.RotatingFileHandler(os.path.join(parent, 'logs', 'keys.log'), maxBytes=10000)
    login_log = logging.handlers.RotatingFileHandler(os.path.join(parent, 'logs', 'logins.log'), maxBytes=10000)
    register_log = logging.handlers.RotatingFileHandler(os.path.join(parent, 'logs', 'registers.log'), maxBytes=10000)

    logger_keys.addHandler(key_log)
    logger_logins.addHandler(login_log)
    logger_regs.addHandler(register_log)

    logger_keys.propagate = 0
    logger_logins.propagate = 0
    logger_regs.propagate = 0


def init_errors(app):
    @app.errorhandler(404)
    def page_not_found(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(500)
    def general_error(error):
        return render_template('errors/500.html'), 500

    @app.errorhandler(502)
    def gateway_error(error):
        return render_template('errors/502.html'), 502


def init_utils(app):
    app.jinja_env.filters['markdown'] = markdown
    app.jinja_env.filters['unix_time'] = unix_time
    app.jinja_env.filters['unix_time_millis'] = unix_time_millis
    app.jinja_env.filters['long2ip'] = long2ip
    app.jinja_env.globals.update(pages=pages)
    app.jinja_env.globals.update(can_register=can_register)
    app.jinja_env.globals.update(can_send_mail=can_send_mail)
    app.jinja_env.globals.update(ctf_name=ctf_name)
    app.jinja_env.globals.update(ctf_theme=ctf_theme)
    app.jinja_env.globals.update(get_configurable_plugins=get_configurable_plugins)
    app.jinja_env.globals.update(get_config=get_config)
    app.jinja_env.globals.update(hide_scores=hide_scores)

    @app.context_processor
    def inject_user():
        if session:
            return dict(session)
        return dict()

    @app.before_request
    def needs_setup():
        if request.path == '/setup' or request.path.startswith('/themes'):
            return
        if not is_setup():
            return redirect(url_for('views.setup'))

    @app.before_request
    def tracker():
        if authed():
            track = Tracking.query.filter_by(ip=get_ip(), team=session['id']).first()
            if not track:
                visit = Tracking(ip=get_ip(), team=session['id'])
                db.session.add(visit)
                db.session.commit()
            else:
                track.date = datetime.datetime.utcnow()
                db.session.commit()
            db.session.close()

    @app.before_request
    def csrf():
        if not session.get('nonce'):
            session['nonce'] = sha512(os.urandom(10))
        if request.method == "POST":
            if session['nonce'] != request.form.get('nonce'):
                abort(403)

    @app.before_request
    def disable_jinja_cache():
        app.jinja_env.cache = {}


@cache.memoize()
def ctf_name():
    name = get_config('ctf_name')
    return name if name else 'CTFd'


@cache.memoize()
def ctf_theme():
    theme = get_config('ctf_theme')
    return theme if theme else ''


@cache.memoize()
def hide_scores():
    return get_config('hide_scores')


def override_template(template, html):
    with app.app_context():
        app.jinja_loader.overriden_templates[template] = html


def pages():
    pages = Pages.query.filter(Pages.route != "index").all()
    return pages


def authed():
    return bool(session.get('id', False))


def is_verified():
    if get_config('verify_emails'):
        team = Teams.query.filter_by(id=session.get('id')).first()
        if team:
            return team.verified
        else:
            return False
    else:
        return True


@cache.memoize()
def is_setup():
    setup = Config.query.filter_by(key='setup').first()
    if setup:
        return setup.value
    else:
        return False


def is_admin():
    if authed():
        return session['admin']
    else:
        return False


@cache.memoize()
def can_register():
    return not bool(get_config('prevent_registration'))


def admins_only(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('admin'):
            return f(*args, **kwargs)
        else:
            return redirect(url_for('auth.login'))
    return decorated_function


@cache.memoize()
def view_after_ctf():
    return bool(get_config('view_after_ctf'))


def is_scoreboard_frozen():
    freeze = get_config('freeze')

    if freeze:
        freeze = int(freeze)
        if freeze < time.time():
            return True

    return False


def ctftime():
    """ Checks whether it's CTF time or not. """

    start = get_config("start")
    end = get_config("end")

    if start:
        start = int(start)
    else:
        start = 0
    if end:
        end = int(end)
    else:
        end = 0

    if start and end:
        if start < time.time() < end:
            # Within the two time bounds
            return True

    if start < time.time() and end == 0:
        # CTF starts on a date but never ends
        return True

    if start == 0 and time.time() < end:
        # CTF started but ends at a date
        return True

    if start == 0 and end == 0:
        # CTF has no time requirements
        return True

    return False


def ctf_started():
    return time.time() > int(get_config("start") or 0)


def ctf_ended():
    if int(get_config("end") or 0):
        return time.time() > int(get_config("end") or 0)
    return False


def user_can_view_challenges():
    config = bool(get_config('view_challenges_unregistered'))
    verify_emails = bool(get_config('verify_emails'))
    if config:
        return authed() or config
    else:
        return authed()


def unix_time(dt):
    return int((dt - datetime.datetime(1970, 1, 1)).total_seconds())


def unix_time_millis(dt):
    return unix_time(dt) * 1000


def unix_time_to_utc(t):
    return datetime.datetime.utcfromtimestamp(t)


def get_ip():
    """ Returns the IP address of the currently in scope request. The approach is to define a list of trusted proxies
     (in this case the local network), and only trust the most recently defined untrusted IP address.
     Taken from http://stackoverflow.com/a/22936947/4285524 but the generator there makes no sense.
     The trusted_proxies regexes is taken from Ruby on Rails.

     This has issues if the clients are also on the local network so you can remove proxies from config.py.

     CTFd does not use IP address for anything besides cursory tracking of teams and it is ill-advised to do much
     more than that if you do not know what you're doing.
    """
    trusted_proxies = app.config['TRUSTED_PROXIES']
    combined = "(" + ")|(".join(trusted_proxies) + ")"
    route = request.access_route + [request.remote_addr]
    for addr in reversed(route):
        if not re.match(combined, addr):  # IP is not trusted but we trust the proxies
            remote_addr = addr
            break
    else:
        remote_addr = request.remote_addr
    return remote_addr


def get_kpm(teamid):  # keys per minute
    one_min_ago = datetime.datetime.utcnow() + datetime.timedelta(minutes=-1)
    return len(db.session.query(WrongKeys).filter(WrongKeys.teamid == teamid, WrongKeys.date >= one_min_ago).all())


def get_themes():
    dir = os.path.join(app.root_path, 'themes')
    return [name for name in os.listdir(dir)
            if os.path.isdir(os.path.join(dir, name)) and name != 'admin']


def get_configurable_plugins():
    dir = os.path.join(app.root_path, 'plugins')
    return [name for name in os.listdir(dir)
            if os.path.isfile(os.path.join(dir, name, 'config.html'))]


def upload_file(file, chalid):
    filename = secure_filename(file.filename)

    if len(filename) <= 0:
        return False

    md5hash = hashlib.md5(os.urandom(64)).hexdigest()

    upload_folder = os.path.join(os.path.normpath(app.root_path), app.config['UPLOAD_FOLDER'])
    if not os.path.exists(os.path.join(upload_folder, md5hash)):
        os.makedirs(os.path.join(upload_folder, md5hash))

    file.save(os.path.join(upload_folder, md5hash, filename))
    db_f = Files(chalid, (md5hash + '/' + filename))
    db.session.add(db_f)
    db.session.commit()
    return db_f.id, (md5hash + '/' + filename)


def delete_file(file_id):
    f = Files.query.filter_by(id=file_id).first_or_404()
    upload_folder = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
    if os.path.exists(os.path.join(upload_folder, f.location)):  # Some kind of os.path.isfile issue on Windows...
        os.unlink(os.path.join(upload_folder, f.location))
    db.session.delete(f)
    db.session.commit()
    return True


@cache.memoize()
def get_config(key):
    with app.app_context():
        value = app.config.get(key)
        if value:
            if value and value.isdigit():
                return int(value)
            elif value and isinstance(value, six.string_types):
                if value.lower() == 'true':
                    return True
                elif value.lower() == 'false':
                    return False
                else:
                    return value
    config = Config.query.filter_by(key=key).first()
    if config and config.value:
        value = config.value
        if value and value.isdigit():
            return int(value)
        elif value and isinstance(value, six.string_types):
            if value.lower() == 'true':
                return True
            elif value.lower() == 'false':
                return False
            else:
                return value
    else:
        set_config(key, None)
        return None


def set_config(key, value):
    config = Config.query.filter_by(key=key).first()
    if config:
        config.value = value
    else:
        config = Config(key, value)
        db.session.add(config)
    db.session.commit()
    return config


@cache.memoize()
def can_send_mail():
    return mailgun() or mailserver()


@cache.memoize()
def mailgun():
    if app.config.get('MAILGUN_API_KEY') and app.config.get('MAILGUN_BASE_URL'):
        return True
    if (get_config('mg_api_key') and get_config('mg_base_url')):
        return True
    return False


@cache.memoize()
def mailserver():
    if ((get_config('mail_server') or app.config.get('MAIL_SERVER')) and (get_config('mail_port') or app.config.get('MAIL_PORT'))):
        return True
    return False


def get_smtp(host, port, username=None, password=None, TLS=None, SSL=None, auth=None):
    if SSL is None:
        smtp = smtplib.SMTP(host, port)
    else:
        smtp = smtplib.SMTP_SSL(host, port)

    if TLS:
        smtp.starttls()

    if auth:
        smtp.login(username, password)
    return smtp


def sendmail(addr, text):
    ctf_name = get_config('ctf_name')
    mailfrom_addr = get_config('mailfrom_addr') or app.config.get('MAILFROM_ADDR')
    mail_server = get_config('mail_server') or app.config.get('MAIL_SERVER')
    mail_port = get_config('mail_port') or app.config.get('MAIL_PORT')
    if mailgun():
        mg_api_key = get_config('mg_api_key') or app.config.get('MAILGUN_API_KEY')
        mg_base_url = get_config('mg_base_url') or app.config.get('MAILGUN_BASE_URL')

        r = requests.post(
            mg_base_url + '/messages',
            auth=("api", mg_api_key),
            data={"from": "{} Admin <{}>".format(ctf_name, mailfrom_addr),
                  "to": [addr],
                  "subject": "Message from {0}".format(ctf_name),
                  "text": text})
        if r.status_code == 200:
            return True
        else:
            return False
    elif mailserver():
        data = {
            'host': mail_server,
            'port': int(mail_port)
        }
        if get_config('mail_username'):
            data['username'] = get_config('mail_username')
        if get_config('mail_password'):
            data['password'] = get_config('mail_password')
        if get_config('mail_tls'):
            data['TLS'] = get_config('mail_tls')
        if get_config('mail_ssl'):
            data['SSL'] = get_config('mail_ssl')
        if get_config('mail_useauth'):
            data['auth'] = get_config('mail_useauth')

        smtp = get_smtp(**data)
        msg = MIMEText(text)
        msg['Subject'] = "Message from {0}".format(ctf_name)
        msg['From'] = mailfrom_addr
        msg['To'] = addr

        smtp.sendmail(msg['From'], [msg['To']], msg.as_string())
        smtp.quit()
        return True
    else:
        return False


def verify_email(addr):
    s = TimedSerializer(app.config['SECRET_KEY'])
    token = s.dumps(addr)
    text = """Please click the following link to confirm your email address for {ctf_name}: {url}/{token}""".format(
        ctf_name=get_config('ctf_name'),
        url=url_for('auth.confirm_user', _external=True),
        token=base64encode(token, urlencode=True)
    )
    sendmail(addr, text)


def rmdir(dir):
    shutil.rmtree(dir, ignore_errors=True)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def validate_url(url):
    return urlparse(url).scheme.startswith('http')


def sha512(string):
    return hashlib.sha512(string).hexdigest()


def base64encode(s, urlencode=False):
    if six.PY3 and isinstance(s, six.string_types):
        s = s.encode('utf-8')
    else:
        # Python 2 support because the base64 module doesnt like unicode
        s = str(s)

    encoded = base64.urlsafe_b64encode(s)
    if six.PY3:
        encoded = encoded.decode('utf-8')
    if urlencode:
        encoded = quote(encoded)
    return encoded


def base64decode(s, urldecode=False):
    if urldecode:
        s = unquote(s)

    if six.PY3 and isinstance(s, six.string_types):
        s = s.encode('utf-8')
    else:
        # Python 2 support because the base64 module doesnt like unicode
        s = str(s)

    decoded = base64.urlsafe_b64decode(s)
    if six.PY3:
        decoded = decoded.decode('utf-8')
    return decoded


def export_ctf(segments=None):
    db = dataset.connect(get_config('SQLALCHEMY_DATABASE_URI'))
    if segments is None:
        segments = ['challenges', 'teams', 'both', 'metadata']

    groups = {
        'challenges': [
            'challenges',
            'files',
            'tags',
            'keys',
            'hints',
        ],
        'teams': [
            'teams',
            'tracking',
            'awards',
        ],
        'both': [
            'solves',
            'wrong_keys',
            'unlocks',
        ],
        'metadata': [
            'alembic_version',
            'config',
            'pages',
        ]
    }

    # Backup database
    backup = io.BytesIO()
    backup_zip = zipfile.ZipFile(backup, 'w')

    for segment in segments:
        group = groups[segment]
        for item in group:
            result = db[item].all()
            result_file = io.BytesIO()
            dataset.freeze(result, format='json', fileobj=result_file)
            result_file.seek(0)
            backup_zip.writestr('db/{}.json'.format(item), result_file.read())

    # Backup uploads
    upload_folder = os.path.join(os.path.normpath(app.root_path), get_config('UPLOAD_FOLDER'))
    for root, dirs, files in os.walk(upload_folder):
        for file in files:
            parent_dir = os.path.basename(root)
            backup_zip.write(os.path.join(root, file), arcname=os.path.join('uploads', parent_dir, file))

    backup_zip.close()
    backup.seek(0)
    return backup


def import_ctf(backup, segments=None, erase=False):
    side_db = dataset.connect(get_config('SQLALCHEMY_DATABASE_URI'))
    if segments is None:
        segments = ['challenges', 'teams', 'both', 'metadata']

    if not zipfile.is_zipfile(backup):
        raise TypeError

    backup = zipfile.ZipFile(backup)

    groups = {
        'challenges': [
            'challenges',
            'files',
            'tags',
            'keys',
            'hints',
        ],
        'teams': [
            'teams',
            'tracking',
            'awards',
        ],
        'both': [
            'solves',
            'wrong_keys',
            'unlocks',
        ],
        'metadata': [
            'alembic_version',
            'config',
            'pages',
        ]
    }

    # Need special handling of metadata
    if 'metadata' in segments:
        meta = groups['metadata']
        segments.remove('metadata')
        meta.remove('alembic_version')

        for item in meta:
            table = side_db[item]
            path = "db/{}.json".format(item)
            data = backup.open(path).read()

            # Some JSON files will be empty
            if data:
                if item == 'config':
                    saved = json.loads(data)
                    for entry in saved['results']:
                        key = entry['key']
                        value = entry['value']
                        set_config(key, value)

                elif item == 'pages':
                    saved = json.loads(data)
                    for entry in saved['results']:
                        route = entry['route']
                        html = entry['html']
                        page = Pages.query.filter_by(route=route).first()
                        if page:
                            page.html = html
                        else:
                            page = Pages(route, html)
                            db.session.add(page)
                        db.session.commit()

    for segment in segments:
        group = groups[segment]
        for item in group:
            table = side_db[item]
            path = "db/{}.json".format(item)
            data = backup.open(path).read()
            if data:
                saved = json.loads(data)
                for entry in saved['results']:
                    entry_id = entry.pop('id', None)
                    # This is a hack to get SQlite to properly accept datetime values from dataset
                    # See Issue #246
                    if get_config('SQLALCHEMY_DATABASE_URI').startswith('sqlite'):
                        for k, v in entry.items():
                            if isinstance(v, six.string_types):
                                try:
                                    entry[k] = datetime.datetime.strptime(v, '%Y-%m-%dT%H:%M:%S')
                                except ValueError as e:
                                    pass
                    table.insert(entry)
            else:
                continue

    # Extracting files
    files = [f for f in backup.namelist() if f.startswith('uploads/')]
    upload_folder = app.config.get('UPLOAD_FOLDER')
    for f in files:
        filename = f.split(os.sep, 1)

        if len(filename) < 2:  # just an empty uploads directory (e.g. uploads/)
            continue

        filename = filename[1]  # Get the second entry in the list (the actual filename)
        full_path = os.path.join(upload_folder, filename)
        dirname = os.path.dirname(full_path)

        # Create any parent directories for the file
        if not os.path.exists(dirname):
            os.makedirs(dirname)

        source = backup.open(f)
        target = file(full_path, "wb")
        with source, target:
            shutil.copyfileobj(source, target)
