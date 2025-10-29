# ============================
# IMPORTACIONES
# ============================
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import func, or_, case
from functools import wraps
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail as SendGridMail
import pandas as pd
from io import BytesIO
from flask import Response
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.config['SECRET_KEY'] = 'Shopping.S1l0.4PP'

basedir = os.path.abspath(os.path.dirname(__file__))
prod_db_url = os.environ.get('DATABASE_URL')
if prod_db_url:
    print("INFO: Conectando a base de datos de PRODUCCIÓN (PostgreSQL)...")
    if prod_db_url.startswith("postgres://"):
        prod_db_url = prod_db_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = prod_db_url
else:
    print("INFO: Usando base de datos LOCAL (SQLite)...")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database/silo.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=15)
app.config['MAIL_DEFAULT_SENDER'] = ('El Silo App', os.environ.get('MAIL_SENDER_EMAIL', 'elsiloapp@gmail.com'))
app.config['UMBRAL_STOCK_BAJO_GLOBAL'] = 10

PLAN_LIMITS = {
    'Gratuito': {'user_limit': 2, 'deposito_limit': 1, 'stock_limit': 25},
    'Básico': {'user_limit': 5, 'deposito_limit': 2, 'stock_limit': 500},
    'Premium': {'user_limit': 15, 'deposito_limit': 5, 'stock_limit': None},
    'Enterprise': {'user_limit': None, 'deposito_limit': None, 'stock_limit': None}
}
DEFAULT_PLAN = 'Gratuito'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, inicie sesión para acceder."
login_manager.login_message_category = "info"


class Tenant(db.Model):
    id = db.Column(db.String(10), primary_key=True)
    plan = db.Column(db.String(50), default=DEFAULT_PLAN, nullable=False)
    users = db.relationship('User', backref='tenant', lazy='dynamic')
    @property
    def user_limit(self): return PLAN_LIMITS.get(self.plan, {}).get('user_limit', 0)
    @property
    def deposito_limit(self): return PLAN_LIMITS.get(self.plan, {}).get('deposito_limit', 0)
    @property
    def stock_limit(self): return PLAN_LIMITS.get(self.plan, {}).get('stock_limit', 0)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=False)
    dni = db.Column(db.String(20), nullable=False)
    nombre = db.Column(db.String(100))
    apellido = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    email_confirmed = db.Column(db.Boolean, default=False)
    __table_args__ = (db.UniqueConstraint('dni', 'tenant_id', name='uq_dni_tenant'),)
    movimientos = db.relationship('Movimiento', backref='user', lazy=True)
    ventas = db.relationship('Venta', backref='user', lazy=True)
    stocks = db.relationship('Stock', backref='user', lazy=True)

class Deposito(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=False)
    nombre_deposito = db.Column(db.String(100), nullable=False)
    ubicacion = db.Column(db.String(200))
    telefono = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    comentarios = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    stocks = db.relationship('Stock', backref='deposito_ref', lazy=True, cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('nombre_deposito', 'tenant_id', name='uq_deposito_tenant'),)

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=False)
    categoria = db.Column(db.String(100), nullable=True)
    producto = db.Column(db.String(100), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    precio_compra = db.Column(db.Float, nullable=False)
    moneda = db.Column(db.String(10), nullable=False)
    deposito_id = db.Column(db.Integer, db.ForeignKey('deposito.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Venta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=False)
    producto = db.Column(db.String(100), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    unidad = db.Column(db.String(20), nullable=False)
    precio_venta = db.Column(db.Float, nullable=False)
    moneda = db.Column(db.String(10), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Movimiento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.String(255), nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Notificacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.String(10), db.ForeignKey('tenant.id'), nullable=True)
    tipo = db.Column(db.String(20), nullable=False)
    titulo = db.Column(db.String(100), nullable=False)
    mensaje = db.Column(db.String(255), nullable=False)
    leido = db.Column(db.Boolean, default=False, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(255), nullable=True)


def log_movimiento(tipo, descripcion, tenant_id, user_id):
    nuevo_movimiento = Movimiento(tipo=tipo, descripcion=descripcion, tenant_id=tenant_id, user_id=user_id)
    db.session.add(nuevo_movimiento)

ALLOWED_EXTENSIONS = {'xlsx'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_confirmation_email(user):
    token = serializer.dumps(user.email, salt='email-confirm-salt')
    confirm_url = url_for('confirm_email', token=token, _external=True)
    sender_email = os.environ.get('MAIL_SENDER_EMAIL')
    if not sender_email: print("Error: MAIL_SENDER_EMAIL no config."); return False
    message = SendGridMail(from_email=sender_email, to_emails=user.email, subject='Confirma tu cuenta en El Silo',
                           html_content=render_template('emails/confirm_email.html', confirm_url=confirm_url, username=user.username))
    try:
        sg_key = os.environ.get('SENDGRID_API_KEY')
        if not sg_key: print("Error: SENDGRID_API_KEY no config."); return False
        sg = SendGridAPIClient(sg_key)
        response = sg.send(message); return response.status_code == 202
    except Exception as e: print(f"Error SG Confirm: {e}"); return False

def send_password_reset_email(user):
    token = serializer.dumps(user.email, salt='password-reset-salt')
    reset_url = url_for('reset_password_token', token=token, _external=True)
    sender_email = os.environ.get('MAIL_SENDER_EMAIL')
    if not sender_email: print("Error: MAIL_SENDER_EMAIL no config."); return False
    message = SendGridMail(from_email=sender_email, to_emails=user.email, subject='Reseteo de contraseña - El Silo',
                           html_content=render_template('emails/reset_email.html', reset_url=reset_url))
    try:
        sg_key = os.environ.get('SENDGRID_API_KEY')
        if not sg_key: print("Error: SENDGRID_API_KEY no config."); return False
        sg = SendGridAPIClient(sg_key)
        response = sg.send(message); return response.status_code == 202
    except Exception as e: print(f"Error SG Reset: {e}"); return False

def send_contact_form_email(user, tenant, nombre, email_origen, telefono, localidad, consulta):
    sender_email = os.environ.get('MAIL_SENDER_EMAIL')
    admin_email = os.environ.get('MAIL_SENDER_EMAIL', 'elsiloapp@gmail.com')
    if not sender_email: print("Error: MAIL_SENDER_EMAIL no está configurado."); return False
    subject = f"Nueva Consulta de Soporte de: {nombre} (Tenant: {tenant})"
    html_content = f"""<p>Has recibido una nueva consulta desde el formulario de la app El Silo.</p><hr><p><strong>Usuario de la App (Logueado):</strong> {user}</p><p><strong>Tenant:</strong> {tenant}</p><hr><h3>Datos del Contacto:</h3><p><strong>Nombre:</strong> {nombre}</p><p><strong>Email de Contacto (para responder):</strong> {email_origen}</p><p><strong>Teléfono:</strong> {telefono if telefono else 'No provisto'}</p><p><strong>Localidad / Provincia:</strong> {localidad}</p><hr><h3>Consulta:</h3><pre style="font-family: sans-serif; white-space: pre-wrap;">{consulta}</pre>"""
    message = SendGridMail(from_email=(f"Formulario App El Silo", sender_email), to_emails=admin_email, subject=subject, html_content=html_content)
    message.reply_to = email_origen
    try:
        sg_key = os.environ.get('SENDGRID_API_KEY')
        if not sg_key: print("Error: SENDGRID_API_KEY no está configurado."); return False
        sg = SendGridAPIClient(sg_key)
        response = sg.send(message); return response.status_code == 202
    except Exception as e: print(f"Error al enviar email de contacto: {e}"); return False

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin': flash('Acceso no autorizado.', 'danger'); return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

@app.before_request
def before_request(): session.permanent = True; app.permanent_session_lifetime = timedelta(minutes=15); session.modified = True


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template("landing.html")

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = None
        
        # 1. Intentar como usuario de empresa (DOMINIO/usuario)
        user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        
        # 2. Si no es un usuario de empresa, intentar como administrador global (solo 'admin')
        if not user and username.lower() == 'admin':
            user = User.query.filter(func.lower(User.username) == 'admin').first()
            
        if user and bcrypt.check_password_hash(user.password, password):
            if not user.email_confirmed and user.role != 'admin':
                flash('Cuenta no confirmada. Revise su email.', 'warning')
                # La redirección es correcta, ya que debe regresar al login.
                return redirect(url_for('login')) 
            else:
                login_user(user, remember=True)
                session.permanent = True
                return redirect(url_for('home'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')
            # CORRECCIÓN: Redirección al propio login para mostrar el error.
            return redirect(url_for('login'))
    return render_template("login.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        domain = request.form.get('domain').upper().strip(); dni = request.form.get('dni').strip()
        nombre = request.form.get('nombre').strip(); apellido = request.form.get('apellido').strip()
        email = request.form.get('email').lower().strip(); password = request.form.get('password')
        confirm_password = request.form.get('confirm_password');
        
        # Validación de errores internos (redirige al mismo formulario de registro)
        if password != confirm_password: flash('Las contraseñas no coinciden.', 'danger'); return redirect(url_for('register'))
        elif len(password) < 8: flash('Contraseña: mínimo 8 caracteres.', 'warning'); return redirect(url_for('register'))
        elif User.query.filter_by(email=email).first(): flash('El email ya está registrado.', 'warning'); return redirect(url_for('register'))
        elif User.query.filter_by(dni=dni, tenant_id=domain).first(): flash(f'DNI {dni} ya registrado para {domain}.', 'warning'); return redirect(url_for('register'))
        elif not domain or len(domain) > 5 or not domain.isalnum(): flash('Dominio: máx 5 letras/núm.', 'warning'); return redirect(url_for('register'))
        else:
            user_count = User.query.filter_by(tenant_id=domain).count()
            tenant = Tenant.query.get(domain)
            if not tenant:
                tenant = Tenant(id=domain, plan=DEFAULT_PLAN); db.session.add(tenant)
                try: db.session.commit()
                except Exception as e: db.session.rollback(); flash(f"Error al crear dominio '{domain}': {e}", "danger"); return redirect(url_for('register'))
            current_limit = tenant.user_limit
            if current_limit is not None and user_count >= current_limit:
                 flash(f"Dominio '{domain}' alcanzó límite ({current_limit}) para plan '{tenant.plan}'.", "warning"); return redirect(url_for('register'))
            username_part = (apellido[:4] + nombre[:2]).lower(); username = f"{domain}/{username_part}"
            counter = 1
            while User.query.filter_by(username=username).first(): username = f"{domain}/{username_part}{counter}"; counter += 1
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            new_user = User(username=username, password=hashed_password, tenant_id=domain, dni=dni, nombre=nombre, apellido=apellido, email=email)
            try:
                db.session.add(new_user); db.session.commit()
                
                # CORRECCIÓN CLAVE: Redirigir a la nueva página de confirmación.
                if send_confirmation_email(new_user):
                     flash(f'Hemos enviado un enlace de confirmación al correo electrónico {email}.', 'success')
                else:
                     flash(f'Registro exitoso, PERO hubo un error al enviar el email de confirmación a {email}. Contacte al admin.', 'warning')
                return redirect(url_for('registro_confirmacion'))
                
            except Exception as e: 
                db.session.rollback(); 
                flash(f'Error registro: {e}', 'danger')
                return redirect(url_for('register')) 
    return render_template('register.html')


@app.route('/confirm/<token>')
def confirm_email(token):
    try: 
        email = serializer.loads(token, salt='email-confirm-salt', max_age=3600*24)
    except (SignatureExpired, BadTimeSignature): 
        flash('Enlace de confirmación inválido o expirado. Intente iniciar sesión para reenviarlo.', 'danger')
        return redirect(url_for('login'))
        
    user = User.query.filter_by(email=email).first_or_404()
    if user.email_confirmed: 
        flash('Cuenta ya confirmada. Inicie sesión.', 'info')
    else: 
        user.email_confirmed = True; 
        db.session.commit()
        flash('¡Cuenta confirmada! Inicie sesión y accede a la aplicación.', 'success')
        
        # NUEVO: Enviar email de bienvenida e información del plan
        if send_welcome_email(user, user.tenant.plan):
            print(f"INFO: Email de bienvenida enviado a {user.email}.")
        else:
            print(f"ERROR: Falló el envío del email de bienvenida a {user.email}.")
        
    return redirect(url_for('login'))

# NUEVA RUTA: Página de confirmación intermedia
@app.route('/registro_confirmacion')
def registro_confirmacion():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('registro_confirmacion.html')

def send_welcome_email(user, plan_name):
    login_url = url_for('login', _external=True)
    sender_email = os.environ.get('MAIL_SENDER_EMAIL')
    if not sender_email: print("Error: MAIL_SENDER_EMAIL no config."); return False
    message = SendGridMail(from_email=sender_email, to_emails=user.email, subject='¡Bienvenido a El Silo!',
                           html_content=render_template('emails/nuevo_usuario.html', login_url=login_url, username=user.username, plan_name=plan_name))
    try:
        sg_key = os.environ.get('SENDGRID_API_KEY')
        if not sg_key: print("Error: SENDGRID_API_KEY no config."); return False
        sg = SendGridAPIClient(sg_key)
        response = sg.send(message); return response.status_code == 202
    except Exception as e: print(f"Error SG Welcome: {e}"); return False

def send_plan_change_email(user, new_plan, user_limit, deposito_limit, stock_limit):
    login_url = url_for('login', _external=True)
    sender_email = os.environ.get('MAIL_SENDER_EMAIL')
    if not sender_email: print("Error: MAIL_SENDER_EMAIL no config."); return False
    
    # Manejar el caso de límites Ilimitados para el email
    ul = user_limit if user_limit is not None else 'Ilimitados'
    dl = deposito_limit if deposito_limit is not None else 'Ilimitados'
    sl = stock_limit if stock_limit is not None else 'Ilimitados'
    
    message = SendGridMail(from_email=sender_email, to_emails=user.email, subject=f'Tu plan en El Silo ha cambiado a {new_plan}!',
                           html_content=render_template('emails/cambio_plan_admin.html', 
                                                       login_url=login_url, 
                                                       tenant_id=user.tenant_id, 
                                                       username=user.username,
                                                       new_plan=new_plan,
                                                       user_limit=ul,
                                                       deposito_limit=dl,
                                                       stock_limit=sl))
    try:
        sg_key = os.environ.get('SENDGRID_API_KEY')
        if not sg_key: print("Error: SENDGRID_API_KEY no config."); return False
        sg = SendGridAPIClient(sg_key)
        response = sg.send(message); return response.status_code == 202
    except Exception as e: print(f"Error SG Plan Change: {e}"); return False

@app.route('/admin/update_tenant_plan/<string:tenant_id>', methods=['POST'])
@login_required
@admin_required
def update_tenant_plan(tenant_id):
     tenant = Tenant.query.get_or_404(tenant_id);
     try:
         new_plan = request.form.get('plan');
         if new_plan not in PLAN_LIMITS: flash(f"Plan inválido.", "danger")
         else: 
             old_plan = tenant.plan
             tenant.plan = new_plan; 
             db.session.commit()
             flash(f"Plan actualizado a '{new_plan}'.", "success")
             
             # NUEVO: Enviar email de cambio de plan a todos los usuarios del tenant.
             if old_plan != new_plan:
                 users_to_notify = User.query.filter_by(tenant_id=tenant_id).all()
                 new_limits = PLAN_LIMITS.get(new_plan, {})
                 
                 for user in users_to_notify:
                     send_plan_change_email(
                         user, 
                         new_plan, 
                         new_limits.get('user_limit'), 
                         new_limits.get('deposito_limit'), 
                         new_limits.get('stock_limit')
                     )
             
     except Exception as e: 
         db.session.rollback(); 
         flash(f"Error: {e}", "danger")
     return redirect(url_for('admin_panel'))

@app.route('/logout')
@login_required
def logout(): logout_user(); flash('Sesión cerrada.', 'info'); return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
     if request.method == 'POST':
        current_user.nombre = request.form.get('nombre').strip()
        current_user.apellido = request.form.get('apellido').strip()
        new_email = request.form.get('email').lower().strip()
        
        # Se guarda el estado de la URL actual para redirigir a la misma vista de perfil.
        target_redirect = url_for('profile') 
        
        if new_email != current_user.email and User.query.filter(User.id != current_user.id, User.email == new_email).first():
            flash('El nuevo correo electrónico ya está en uso.', 'danger'); return redirect(target_redirect)
        current_user.email = new_email
        current_password = request.form.get('current_password'); new_password = request.form.get('new_password'); confirm_new_password = request.form.get('confirm_new_password')
        password_changed = False
        if current_password or new_password or confirm_new_password:
            if not current_password: flash('Debe ingresar su contraseña actual para cambiarla.', 'warning'); return redirect(target_redirect)
            elif not bcrypt.check_password_hash(current_user.password, current_password): flash('Contraseña actual incorrecta.', 'danger'); return redirect(target_redirect)
            elif new_password != confirm_new_password: flash('Nuevas contraseñas no coinciden.', 'danger'); return redirect(target_redirect)
            elif len(new_password) < 8: flash('Nueva contraseña: mínimo 8 caracteres.', 'warning'); return redirect(target_redirect)
            else: current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8'); password_changed = True
        try:
            db.session.commit()
            if password_changed: flash('Datos personales y contraseña actualizados.', 'success')
            elif not (current_password or new_password or confirm_new_password): flash('Datos personales actualizados.', 'success')
            return redirect(target_redirect)
        except Exception as e: db.session.rollback(); flash(f'Error al actualizar: {e}', 'danger'); return redirect(target_redirect)
     return render_template("profile.html")

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form.get('email').lower().strip()
        user = User.query.filter_by(email=email).first()
        if user:
            if send_password_reset_email(user): flash('Email enviado con instrucciones.', 'info')
            else: flash('Error al intentar enviar email de reseteo. Contacte al administrador.', 'danger')
        else: flash('Email no encontrado.', 'warning')
        # CORRECCIÓN: Redirección al propio formulario de forgot_password.
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    if current_user.is_authenticated: return redirect(url_for('home'))
    try: email = serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except (SignatureExpired, BadTimeSignature): flash('Enlace inválido o expirado.', 'danger'); return redirect(url_for('forgot_password'))
    user = User.query.filter_by(email=email).first_or_404()
    if request.method == 'POST':
        password = request.form.get('password'); confirm_password = request.form.get('confirm_password')
        
        # Redirige a la misma URL con el token para mostrar el error.
        target_redirect = url_for('reset_password_token', token=token)
        
        if password != confirm_password: flash('Las contraseñas no coinciden.', 'danger'); return redirect(target_redirect)
        elif len(password) < 8: flash('Contraseña: mínimo 8 caracteres.', 'warning'); return redirect(target_redirect)
        else: 
            user.password = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.commit()
            # Si tiene éxito, SÍ debe redirigir al login
            flash('Contraseña actualizada. Inicie sesión.', 'success'); return redirect(url_for('login'))
            
    return render_template('reset_password.html', token=token)

@app.route("/home")
@login_required
def home(): return render_template("home.html")

@app.route("/info")
@login_required
def info():
    return render_template("info.html")

@app.route("/por-que-el-silo")
def features_page():
    return render_template("features.html")

@app.route("/precios")
def pricing_page():
    return render_template("pricing.html", PLAN_LIMITS=PLAN_LIMITS)

@app.route("/privacidad")
def privacy_page():
    return render_template("privacy.html")

@app.route("/cookies")
def cookies_page():
    return render_template("cookies.html")

@app.route("/accesibilidad")
def accessibility_page():
    return render_template("accessibility.html")

@app.route('/send_contact_email', methods=['POST'])
@login_required
def send_contact_email():
    try:
        nombre = request.form.get('nombre'); email_origen = request.form.get('email_origen'); telefono = request.form.get('telefono'); localidad = request.form.get('localidad'); consulta = request.form.get('consulta')
        user_logueado = current_user.username; tenant_logueado = current_user.tenant_id
        success = send_contact_form_email(user_logueado, tenant_logueado, nombre, email_origen, telefono, localidad, consulta)
        if success: flash('Tu consulta ha sido enviada con éxito. Te responderemos pronto.', 'success')
        else: flash('Hubo un error al enviar tu consulta. Por favor, inténtalo de nuevo o contacta al administrador.', 'danger')
    except Exception as e: flash(f'Ocurrió un error inesperado: {e}', 'danger')
    return redirect(url_for('info'))


@app.route("/stocks")
@login_required
def stocks():
    current_tenant_id = current_user.tenant_id
    filtro_deposito_id = request.args.get("deposito", "", type=int)
    busqueda = request.args.get("q", "")
    filtro_categoria = request.args.get("categoria", "")
    query = Stock.query.filter_by(tenant_id=current_tenant_id)
    if filtro_deposito_id: query = query.filter_by(deposito_id=filtro_deposito_id)
    if busqueda: query = query.filter(Stock.producto.ilike(f"%{busqueda}%"))
    if filtro_categoria: query = query.filter(Stock.categoria == filtro_categoria)
    stocks = query.order_by(Stock.producto).all()
    stock_count = len(stocks)
    depositos = Deposito.query.filter_by(tenant_id=current_tenant_id).order_by(Deposito.nombre_deposito).all()
    unidades_db = {u[0] for u in db.session.query(Stock.unidad).filter_by(tenant_id=current_tenant_id).distinct().all()}
    unidades_completas = sorted(list(unidades_db.union({'Unidades', 'Kg', 'Litros', 'Rollos', 'Bolsas', 'Metros'})))
    categorias_db = {c[0] for c in db.session.query(Stock.categoria).filter(Stock.tenant_id==current_tenant_id, Stock.categoria.isnot(None)).distinct().all()}
    categorias_completas = sorted(list(categorias_db.union({'Semillas', 'Fertilizantes', 'Herbicidas', 'Repuestos', 'Insumos Varios'})))
    return render_template("stocks.html", stocks=stocks, stock_count=stock_count, depositos=depositos, filtro_id=filtro_deposito_id, busqueda=busqueda, unidades=unidades_completas, categorias=categorias_completas, filtro_cat=filtro_categoria)

@app.route("/add_insumo", methods=["POST"])
@login_required
def add_insumo():
    current_tenant = current_user.tenant; stock_count = Stock.query.filter_by(tenant_id=current_tenant.id).count()
    if current_tenant.stock_limit is not None and stock_count >= current_tenant.stock_limit:
        flash(f"Límite de {current_tenant.stock_limit} productos alcanzado (Plan {current_tenant.plan}).", "warning"); return redirect(url_for("stocks"))
    try:
        cantidad = int(request.form["cantidad"]); precio = float(request.form["precio"])
        if cantidad <= 0 or precio < 0: flash("Cantidad/precio deben ser positivos.", "danger"); return redirect(url_for("stocks"))
        unidad_lista = request.form.get("unidad"); unidad_custom = request.form.get("unidad_personalizada", "").strip(); unidad_final = unidad_custom if unidad_custom else unidad_lista
        if not unidad_final: flash("Debe seleccionar o escribir una unidad.", "danger"); return redirect(url_for("stocks"))
        categoria_form = request.form.get("categoria", "").strip()
        nuevo_stock = Stock(producto=request.form["producto"].strip(), cantidad=cantidad, unidad=unidad_final, categoria=categoria_form if categoria_form else None, precio_compra=precio, moneda=request.form["moneda"], deposito_id=int(request.form["deposito"]), tenant_id=current_user.tenant_id, user_id=current_user.id)
        db.session.add(nuevo_stock); log_movimiento("STOCK", f"Agregado: {cantidad} {nuevo_stock.unidad} de {nuevo_stock.producto}", current_user.tenant_id, current_user.id); db.session.commit(); flash("Stock agregado.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for("stocks"))

@app.route("/edit_insumo/<int:id>", methods=["POST"])
@login_required
def edit_insumo(id):
    stock = Stock.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
    try:
        unidad_lista = request.form.get("unidad"); unidad_custom = request.form.get("unidad_personalizada", "").strip(); unidad_final = unidad_custom if unidad_custom else unidad_lista
        if not unidad_final: flash("Debe seleccionar o escribir una unidad.", "danger"); return redirect(url_for("stocks"))
        stock.producto = request.form["producto"].strip(); stock.cantidad = int(request.form["cantidad"]); stock.unidad = unidad_final; stock.categoria = request.form.get("categoria", "").strip() or None; stock.precio_compra = float(request.form["precio"]); stock.moneda = request.form["moneda"]; stock.deposito_id = int(request.form["deposito"])
        log_movimiento("STOCK", f"Editado: stock {stock.producto}", current_user.tenant_id, current_user.id); db.session.commit(); flash("Stock actualizado.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for("stocks"))

@app.route("/delete_insumo/<int:id>")
@login_required
def delete_insumo(id):
    stock = Stock.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
    try:
        producto_nombre = stock.producto; db.session.delete(stock); log_movimiento("STOCK", f"Eliminado: stock {producto_nombre}", current_user.tenant_id, current_user.id); db.session.commit(); flash(f"Stock '{producto_nombre}' eliminado.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for("stocks"))

@app.route('/import_stock', methods=['POST'])
@login_required
def import_stock():
    current_tenant = current_user.tenant; stock_count = Stock.query.filter_by(tenant_id=current_tenant.id).count()
    if current_tenant.plan in ['Gratuito', 'Básico']: flash("Importación masiva solo en planes Premium o Enterprise.", "warning"); return redirect(url_for('stocks'))
    if current_tenant.stock_limit is not None and stock_count >= current_tenant.stock_limit: flash(f"Límite de {current_tenant.stock_limit} productos alcanzado (Plan {current_tenant.plan}).", "warning"); return redirect(url_for('stocks'))
    if 'file' not in request.files: flash('No se encontró archivo.', 'danger'); return redirect(url_for('stocks'))
    file = request.files['file'];
    if file.filename == '': flash('No se seleccionó archivo.', 'warning'); return redirect(url_for('stocks'))
    if file and allowed_file(file.filename):
        filepath = None
        try:
            if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename)); file.save(filepath)
            df = pd.read_excel(filepath); depositos_map = {d.nombre_deposito: d.id for d in Deposito.query.filter_by(tenant_id=current_user.tenant_id).all()}
            required_columns = ['Producto', 'Categoria', 'Cantidad', 'Unidad', 'Precio Compra', 'Moneda', 'Deposito']
            if not all(col in df.columns for col in required_columns): 
                flash(f"Columnas requeridas: {', '.join(required_columns)}", 'danger')
                return redirect(url_for('stocks'))
            
            stocks_a_crear = []; filas_omitidas = []; import_count = 0
            for index, row in df.iterrows():
                if current_tenant.stock_limit is not None and (stock_count + import_count) >= current_tenant.stock_limit: 
                    flash(f"Importación parcial: Límite de {current_tenant.stock_limit} productos alcanzado.", "warning")
                    break
                deposito_nombre = row['Deposito']
                if deposito_nombre in depositos_map:
                    nuevo_stock = Stock(producto=row['Producto'], cantidad=int(row['Cantidad']), unidad=row['Unidad'], categoria=row['Categoria'].strip() if pd.notna(row['Categoria']) else None, precio_compra=float(row['Precio Compra']), moneda=row['Moneda'], deposito_id=depositos_map[deposito_nombre], tenant_id=current_user.tenant_id, user_id=current_user.id)
                    stocks_a_crear.append(nuevo_stock); log_movimiento("STOCK", f"Importación: {row['Producto']} ({row['Cantidad']} {nuevo_stock.unidad})", current_user.tenant_id, current_user.id); import_count += 1
                else: filas_omitidas.append(index + 2)
            
            if stocks_a_crear: db.session.add_all(stocks_a_crear); db.session.commit(); flash(f"{import_count} productos importados.", "success")
            if filas_omitidas: flash(f"Filas omitidas (depósito no encontrado): {', '.join(map(str, filas_omitidas))}", "warning")
            
        except Exception as e: 
            db.session.rollback()
            flash(f"Error procesando archivo: {e}", "danger")
        finally:
            if filepath and os.path.exists(filepath): 
                os.remove(filepath)
        
        return redirect(url_for('stocks'))
    else: 
        flash('Formato no permitido (.xlsx).', 'danger')
        return redirect(url_for('stocks'))


@app.route("/ventas")
@login_required
def ventas():
    current_tenant_id = current_user.tenant_id
    filtro_producto_id = request.args.get("producto", "", type=int); filtro_fecha_inicio_str = request.args.get("inicio", ""); filtro_fecha_fin_str = request.args.get("fin", "")
    filtro_fecha_inicio = None;
    if filtro_fecha_inicio_str: 
        try: filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio_str, '%Y-%m-%d') 
        except ValueError: flash("Formato de fecha de inicio inválido.", "warning")
    filtro_fecha_fin = None;
    if filtro_fecha_fin_str: 
        try: filtro_fecha_fin = datetime.strptime(filtro_fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) 
        except ValueError: flash("Formato de fecha de fin inválido.", "warning")
    productos_para_filtro = db.session.query(Stock.id, Stock.producto).filter(Stock.tenant_id==current_tenant_id).distinct(Stock.producto).order_by(Stock.producto).all()
    query_ventas = Venta.query.filter_by(tenant_id=current_tenant_id)
    if filtro_producto_id:
        stock_seleccionado = Stock.query.get(filtro_producto_id)
        if stock_seleccionado: query_ventas = query_ventas.filter(Venta.producto == stock_seleccionado.producto)
    if filtro_fecha_inicio: query_ventas = query_ventas.filter(Venta.fecha >= filtro_fecha_inicio)
    if filtro_fecha_fin: query_ventas = query_ventas.filter(Venta.fecha <= filtro_fecha_fin)
    ventas_registradas = query_ventas.order_by(Venta.fecha.desc()).all()
    ventas_count = len(ventas_registradas)
    productos_modal = Stock.query.filter(Stock.tenant_id==current_tenant_id, Stock.cantidad > 0).order_by(Stock.producto).all()
    return render_template("ventas.html", productos=productos_modal, ventas=ventas_registradas, ventas_count=ventas_count, productos_filtro=productos_para_filtro, filtro_prod_id=filtro_producto_id, filtro_inicio=filtro_fecha_inicio_str, filtro_fin=filtro_fecha_fin_str)

@app.route('/add_venta', methods=['POST'])
@login_required
def add_venta():
    try:
        stock_id = int(request.form['stock_id']); cantidad_venta = int(request.form['cantidad'])
        stock = Stock.query.filter_by(id=stock_id, tenant_id=current_user.tenant_id).first_or_404()
        if stock.cantidad < cantidad_venta: flash(f"Stock insuficiente.", "warning"); return redirect(url_for('ventas'))
        stock.cantidad -= cantidad_venta
        precio_venta_form = float(request.form['precio_venta']); moneda_form = request.form['moneda']
        nueva_venta = Venta(producto=stock.producto, cantidad=cantidad_venta, unidad=stock.unidad, precio_venta=precio_venta_form, moneda=moneda_form, tenant_id=current_user.tenant_id, user_id=current_user.id)
        db.session.add(nueva_venta); log_movimiento("VENTA", f"Venta: {cantidad_venta} {stock.unidad} de {stock.producto} por {precio_venta_form} {moneda_form}", current_user.tenant_id, current_user.id); db.session.commit(); flash("Venta registrada.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for('ventas'))

@app.route("/edit_venta/<int:id>", methods=["POST"])
@login_required
def edit_venta(id):
     venta = Venta.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
     stock_items = Stock.query.filter_by(producto=venta.producto, tenant_id=current_user.tenant_id).all()
     if not stock_items: flash(f"Stock no encontrado.", "danger"); return redirect(url_for('ventas'))
     stock = stock_items[0]
     try:
         cantidad_original = venta.cantidad; cantidad_nueva = int(request.form['cantidad']); diferencia = cantidad_nueva - cantidad_original
         if diferencia > 0 and stock.cantidad < diferencia: flash(f"Stock insuficiente para aumentar cantidad.", "warning"); return redirect(url_for('ventas'))
         stock.cantidad -= diferencia
         precio_venta_form = float(request.form['precio_venta']); moneda_form = request.form['moneda']
         venta.cantidad = cantidad_nueva; venta.precio_venta = precio_venta_form; venta.moneda = moneda_form
         log_movimiento("VENTA", f"Edición Venta ID {id}. Nueva cant: {cantidad_nueva} ({precio_venta_form} {moneda_form})", current_user.tenant_id, current_user.id); db.session.commit(); flash("Venta actualizada.", "success")
     except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
     return redirect(url_for('ventas'))

@app.route("/delete_venta/<int:id>")
@login_required
def delete_venta(id):
    venta = Venta.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
    stock = Stock.query.filter_by(producto=venta.producto, tenant_id=current_user.tenant_id).first()
    try:
        log_desc = f"Venta ID {id} eliminada ({venta.cantidad} {venta.unidad} de {venta.producto})."
        if stock: stock.cantidad += venta.cantidad; log_desc += " Stock restaurado."
        else: log_desc += " Stock no encontrado para restaurar."
        db.session.delete(venta); log_movimiento("VENTA", log_desc, current_user.tenant_id, current_user.id); db.session.commit(); flash("Venta eliminada.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for('ventas'))


@app.route("/depositos")
@login_required
def depositos():
    todos_los_depositos = Deposito.query.filter_by(tenant_id=current_user.tenant_id).order_by(Deposito.nombre_deposito).all()
    return render_template("depositos.html", depositos=todos_los_depositos)

@app.route("/add_deposito", methods=["POST"])
@login_required
def add_deposito():
    current_tenant = current_user.tenant; deposito_count = Deposito.query.filter_by(tenant_id=current_tenant.id).count()
    if current_tenant.deposito_limit is not None and deposito_count >= current_tenant.deposito_limit: flash(f"Límite de {current_tenant.deposito_limit} depósitos alcanzado (Plan {current_tenant.plan}).", "warning"); return redirect(url_for("depositos"))
    nombre = request.form["nombre_deposito"].strip()
    if Deposito.query.filter_by(nombre_deposito=nombre, tenant_id=current_user.tenant_id).first(): flash(f"Depósito '{nombre}' ya existe.", "danger"); return redirect(url_for("depositos"))
    try:
        nuevo_deposito = Deposito(nombre_deposito=nombre, ubicacion=request.form["ubicacion"], telefono=request.form.get("telefono", "").strip() or None, email=request.form.get("email", "").strip() or None, comentarios=request.form["comentarios"], tenant_id=current_user.tenant_id, user_id=current_user.id)
        db.session.add(nuevo_deposito); log_movimiento("DEPOSITO", f"Creado: depósito {nombre}", current_user.tenant_id, current_user.id); db.session.commit(); flash(f"Depósito '{nombre}' creado.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    # CORRECCIÓN: Redirecciona a la página de depósitos
    return redirect(url_for("depositos"))

@app.route("/edit_deposito/<int:id>", methods=["POST"])
@login_required
def edit_deposito(id):
     deposito = Deposito.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
     try:
         nuevo_nombre = request.form["nombre_deposito"].strip()
         if nuevo_nombre != deposito.nombre_deposito and Deposito.query.filter(Deposito.id != id, Deposito.nombre_deposito == nuevo_nombre, Deposito.tenant_id == current_user.tenant_id).first(): flash(f"Ya existe depósito '{nuevo_nombre}'.", "warning"); return redirect(url_for("depositos"))
         deposito.nombre_deposito = nuevo_nombre; deposito.ubicacion = request.form["ubicacion"]; deposito.telefono = request.form.get("telefono", "").strip() or None; deposito.email = request.form.get("email", "").strip() or None; deposito.comentarios = request.form["comentarios"]
         log_movimiento("DEPOSITO", f"Editado: depósito {deposito.nombre_deposito}", current_user.tenant_id, current_user.id); db.session.commit(); flash("Depósito actualizado.", "success")
     except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
     # CORRECCIÓN: Redirecciona a la página de depósitos
     return redirect(url_for("depositos"))

@app.route("/delete_deposito/<int:id>")
@login_required
def delete_deposito(id):
     deposito = Deposito.query.filter_by(id=id, tenant_id=current_user.tenant_id).first_or_404()
     if deposito.stocks: flash(f"No eliminar '{deposito.nombre_deposito}' (contiene stocks).", "danger"); return redirect(url_for("depositos"))
     try:
         nombre_deposito = deposito.nombre_deposito; db.session.delete(deposito); log_movimiento("DEPOSITO", f"Eliminado: depósito {nombre_deposito}", current_user.tenant_id, current_user.id); db.session.commit(); flash(f"Depósito '{nombre_deposito}' eliminado.", "success")
     except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
     # CORRECCIÓN: Redirecciona a la página de depósitos
     return redirect(url_for("depositos"))

@app.route('/import_depositos', methods=['POST'])
@login_required
def import_depositos():
    current_tenant = current_user.tenant; deposito_count = Deposito.query.filter_by(tenant_id=current_tenant.id).count()
    if current_tenant.plan in ['Gratuito']: flash("Importación masiva no disponible en el Plan Gratuito.", "warning"); return redirect(url_for('depositos'))
    if current_tenant.deposito_limit is not None and deposito_count >= current_tenant.deposito_limit: flash(f"Límite de {current_tenant.deposito_limit} depósitos alcanzado (Plan {current_tenant.plan}).", "warning"); return redirect(url_for('depositos'))
    if 'file' not in request.files: flash('No se encontró archivo.', 'danger'); return redirect(url_for('depositos'))
    file = request.files['file']
    if file.filename == '': flash('No se seleccionó archivo.', 'warning'); return redirect(url_for('depositos'))
    
    filepath = None
    if file and allowed_file(file.filename):
        try:
            if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename)); file.save(filepath)
            
            df = pd.read_excel(filepath)
            required_columns = ['Nombre Deposito', 'Ubicacion', 'Comentarios', 'Telefono', 'Email']
            
            if not all(col in df.columns for col in required_columns): 
                flash(f"Error de formato: Columnas requeridas: {', '.join(required_columns)}", 'danger')
                return redirect(url_for('depositos'))

            depositos_existentes = {d.nombre_deposito for d in Deposito.query.filter_by(tenant_id=current_user.tenant_id).all()}
            depositos_a_crear = []; duplicados_omitidos = []; import_count = 0
            
            for index, row in df.iterrows():
                if current_tenant.deposito_limit is not None and (deposito_count + import_count) >= current_tenant.deposito_limit: 
                    flash(f"Importación parcial: Límite de {current_tenant.deposito_limit} depósitos alcanzado.", "warning")
                    break
                
                nombre = str(row['Nombre Deposito']).strip()
                if not nombre:
                    duplicados_omitidos.append(f"Fila {index + 2}: Nombre vacío")
                    continue

                if nombre not in depositos_existentes:
                    nuevo_deposito = Deposito(
                        nombre_deposito=nombre, 
                        ubicacion=str(row['Ubicacion']).strip() if pd.notna(row['Ubicacion']) else None, 
                        telefono=str(row['Telefono']).strip() if pd.notna(row['Telefono']) else None, 
                        email=str(row['Email']).strip() if pd.notna(row['Email']) else None, 
                        comentarios=str(row['Comentarios']).strip() if pd.notna(row['Comentarios']) else None, 
                        tenant_id=current_user.tenant_id, 
                        user_id=current_user.id
                    )
                    depositos_a_crear.append(nuevo_deposito)
                    log_movimiento("DEPOSITO", f"Importación: depósito '{nombre}'", current_user.tenant_id, current_user.id)
                    depositos_existentes.add(nombre)
                    import_count += 1
                else: 
                    duplicados_omitidos.append(nombre)
            
            if depositos_a_crear: 
                db.session.add_all(depositos_a_crear)
                db.session.commit()
                flash(f"{import_count} depósitos importados.", "success")
                
            if duplicados_omitidos: 
                flash(f"Omitidos (ya existían o inválidos): {', '.join(duplicados_omitidos[:5])}{' y más' if len(duplicados_omitidos)>5 else ''}", "warning")
                
        except Exception as e: 
            db.session.rollback()
            flash(f"Error procesando archivo: {e}", "danger")
        finally:
             if filepath and os.path.exists(filepath): 
                 os.remove(filepath)
                 
        return redirect(url_for('depositos'))
    else: 
        flash('Formato no permitido (.xlsx).', 'danger')
        return redirect(url_for('depositos'))


@app.route("/reportes_y_movimientos")
@login_required
def reportes_y_movimientos():
    current_tenant_id = current_user.tenant_id
    
    # Consultas robustas para los resúmenes
    total_ventas = db.session.query(Venta.moneda, func.sum(Venta.precio_venta), func.sum(Venta.cantidad)).filter(Venta.tenant_id == current_tenant_id).group_by(Venta.moneda).all()
    valor_stock = db.session.query(Stock.moneda, func.sum(Stock.precio_compra)).filter(Stock.tenant_id == current_tenant_id).group_by(Stock.moneda).all()
    resumen_depositos = db.session.query(Deposito.nombre_deposito, func.count(Stock.id)).outerjoin(Stock, Deposito.id == Stock.deposito_id).filter(Deposito.tenant_id == current_tenant_id).group_by(Deposito.nombre_deposito).order_by(Deposito.nombre_deposito).all()
    top_productos = db.session.query(Venta.producto, func.sum(Venta.cantidad)).filter(Venta.tenant_id == current_tenant_id).group_by(Venta.producto).order_by(func.sum(Venta.cantidad).desc()).limit(5).all()
    
    filtro = request.args.get("tipo", "")
    query = Movimiento.query.filter_by(tenant_id=current_tenant_id)
    
    if filtro: query = query.filter_by(tipo=filtro)
    
    # CORRECCIÓN CLAVE: Usar OUTERJOIN para que no falle si el usuario es null o fue borrado.
    movimientos_consulta = query.outerjoin(User, Movimiento.user_id == User.id)
    
    movimientos = movimientos_consulta.add_columns(
        Movimiento.id, 
        Movimiento.fecha, 
        Movimiento.tipo, 
        Movimiento.descripcion, 
        func.coalesce(User.username, '- (Eliminado)').label('username') # Asegurar que el username no sea None
    ).order_by(Movimiento.fecha.desc()).all()
    
    movimientos_count = len(movimientos)
    
    # Recargar datos de apoyo
    depositos = Deposito.query.filter_by(tenant_id=current_tenant_id).order_by(Deposito.nombre_deposito).all()
    productos_en_stock = {row[0] for row in db.session.query(Stock.producto).filter(Stock.tenant_id == current_tenant_id).distinct().all()}
    productos_vendidos = {row[0] for row in db.session.query(Venta.producto).filter(Venta.tenant_id == current_tenant_id).distinct().all()}
    lista_completa_productos = sorted(list(productos_en_stock.union(productos_vendidos)))
    usuarios_del_tenant = User.query.filter_by(tenant_id=current_tenant_id).order_by(User.username).all()
    categorias_db = {c[0] for c in db.session.query(Stock.categoria).filter(Stock.tenant_id==current_tenant_id, Stock.categoria.isnot(None)).distinct().all()}
    categorias_completas = sorted(list(categorias_db))

    return render_template("reportes_y_movimientos.html", 
        movimientos=movimientos, 
        movimientos_count=movimientos_count, 
        filtro=filtro, 
        total_ventas=total_ventas, 
        valor_stock=valor_stock, 
        resumen_depositos=resumen_depositos, 
        top_productos=top_productos, 
        depositos=depositos, 
        productos=lista_completa_productos, 
        usuarios=usuarios_del_tenant, 
        categorias=categorias_completas)

@app.route('/clear_movimientos', methods=['POST'], endpoint='clear_movimientos')
@login_required
def clear_movimientos():
    try: Movimiento.query.filter_by(tenant_id=current_user.tenant_id).delete(); db.session.commit(); flash("Historial borrado.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_stock/<string:formato>')
@login_required
def exportar_stock(formato):
    try:
        current_tenant_id = current_user.tenant_id
        filtro_deposito_id = request.args.get("deposito", "", type=int)
        busqueda = request.args.get("q", "")
        filtro_categoria = request.args.get("categoria", "")
        
        query = Stock.query.filter_by(tenant_id=current_tenant_id).join(Deposito, Stock.deposito_id == Deposito.id).options(db.joinedload(Stock.deposito_ref))
        
        if filtro_deposito_id: query = query.filter(Stock.deposito_id == filtro_deposito_id)
        if busqueda: query = query.filter(Stock.producto.ilike(f"%{busqueda}%"))
        if filtro_categoria: query = query.filter(Stock.categoria == filtro_categoria)
        
        stocks_export = query.order_by(Deposito.nombre_deposito, Stock.producto).all()
        
        if not stocks_export:
            flash("No hay stock para exportar con los filtros aplicados.", "info")
            return redirect(url_for('stocks'))
            
        data_list = []
        for s in stocks_export:
            # Garantizar que precio_compra sea float o 0 para evitar errores de tipo
            precio_compra_float = float(s.precio_compra) if s.precio_compra is not None else 0.0
            
            # Cálculo seguro de costo unitario y valor total
            costo_unitario = precio_compra_float / float(s.cantidad) if s.cantidad > 0 else 0.0
            valor_total = precio_compra_float
            
            data_list.append({
                'Producto': s.producto, 
                'Categoria': s.categoria if s.categoria else '-', 
                'Deposito': s.deposito_ref.nombre_deposito, 
                'Cantidad': s.cantidad, 
                'Unidad': s.unidad, 
                'Moneda': s.moneda, 
                'Precio Compra (Total Lote)': valor_total, 
                'Costo Unitario Est.': costo_unitario, 
                'Valor Total Est.': valor_total
            })
            
        titulo_reporte = "Reporte de Stock"
        df = pd.DataFrame(data_list)
        df = df[['Producto', 'Categoria', 'Deposito', 'Cantidad', 'Unidad', 'Moneda', 'Precio Compra (Total Lote)', 'Costo Unitario Est.', 'Valor Total Est.']]
        
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name=titulo_reporte)
                # El resto de formatos sigue comentado para debugear
            output.seek(0)
            return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_stock.xlsx"})
            
        elif formato == 'pdf':
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
            elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)]
            
            df_pdf = df.copy()
            # Conversiones para PDF
            df_pdf['Cantidad'] = df_pdf['Cantidad'].map('{:,.0f}'.format)
            df_pdf['Precio Compra (Total Lote)'] = df_pdf['Precio Compra (Total Lote)'].map('{:,.2f}'.format)
            df_pdf['Costo Unitario Est.'] = df_pdf['Costo Unitario Est.'].map('{:,.2f}'.format)
            df_pdf['Valor Total Est.'] = df_pdf['Valor Total Est.'].map('{:,.2f}'.format)
            
            pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist()
            table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (3, 1), (-1, -1), 'RIGHT')
            ]))
            elements.append(table)
            doc.build(elements)
            buffer.seek(0)
            return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_stock.pdf"})
        
        return redirect(url_for('stocks'))
    except Exception as e:
        # Esto imprimirá el error exacto en tu consola, lo que es VITAL
        app.logger.error(f"Error en exportar_stock: {e}", exc_info=True)
        flash(f"Error interno al exportar stock.", "danger")
        return redirect(url_for('stocks'))
    
@app.route('/exportar_ventas/<string:formato>')
@login_required
def exportar_ventas(formato):
    try:
        current_tenant_id = current_user.tenant_id
        filtro_producto_id = request.args.get("producto", "", type=int)
        filtro_fecha_inicio_str = request.args.get("inicio", "")
        filtro_fecha_fin_str = request.args.get("fin", "")
        filtro_fecha_inicio = None
        if filtro_fecha_inicio_str: 
            try: filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio_str, '%Y-%m-%d') 
            except ValueError: pass
        filtro_fecha_fin = None
        if filtro_fecha_fin_str: 
            try: filtro_fecha_fin = datetime.strptime(filtro_fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) 
            except ValueError: pass
        
        # CAMBIO CLAVE 1: Unir Venta con Usuario (LEFT OUTER JOIN)
        query = Venta.query.outerjoin(User, Venta.user_id == User.id).filter(Venta.tenant_id == current_tenant_id)
        
        producto_nombre_filtro = None
        if filtro_producto_id:
            stock_sel = Stock.query.get(filtro_producto_id)
            if stock_sel: query = query.filter(Venta.producto == stock_sel.producto); producto_nombre_filtro = stock_sel.producto
        if filtro_fecha_inicio: query = query.filter(Venta.fecha >= filtro_fecha_inicio)
        if filtro_fecha_fin: query = query.filter(Venta.fecha <= filtro_fecha_fin)

        # Seleccionar las columnas, incluyendo el nombre de usuario
        ventas_registradas = query.add_columns(
            Venta.fecha, Venta.producto, Venta.cantidad, Venta.unidad, 
            Venta.moneda, Venta.precio_venta, func.coalesce(User.username, '-').label('username')
        ).order_by(Venta.fecha.desc()).all()

        if not ventas_registradas: flash("No hay ventas para exportar con los filtros aplicados.", "info"); return redirect(url_for('ventas'))
        
        data_list = []
        productos_stock_info = {s.producto: (float(s.precio_compra / s.cantidad) if s.cantidad > 0 and s.precio_compra is not None else 0.0) for s in Stock.query.filter_by(tenant_id=current_user.tenant_id)}
        
        # CAMBIO CLAVE 2: Iterar sobre los resultados de la consulta modificada
        for v in ventas_registradas:
            costo_unitario_est = productos_stock_info.get(v.producto, 0.0)
            costo_total_est = costo_unitario_est * v.cantidad
            ganancia_est = v.precio_venta - costo_total_est
            
            data_list.append({
                'Fecha': v.fecha.strftime('%Y-%m-%d %H:%M'), 
                'Producto': v.producto, 
                'Cantidad': v.cantidad, 
                'Unidad': v.unidad, 
                'Moneda': v.moneda, 
                'Precio Venta': v.precio_venta, 
                'Costo Total Est.': costo_total_est, 
                'Ganancia Est.': ganancia_est,
                'Usuario': v.username # Nuevo campo añadido
            })
            
        titulo_reporte = "Reporte de Ventas"
        df = pd.DataFrame(data_list)
        
        # CAMBIO CLAVE 3: Reordenar la lista de columnas para incluir 'Usuario'
        df = df[['Fecha', 'Producto', 'Cantidad', 'Unidad', 'Moneda', 'Precio Venta', 'Costo Total Est.', 'Ganancia Est.', 'Usuario']]
        
        if producto_nombre_filtro: titulo_reporte += f" - Producto: {producto_nombre_filtro}"
        if filtro_fecha_inicio_str or filtro_fecha_fin_str: f_inicio = filtro_fecha_inicio.strftime('%d/%m/%Y') if filtro_fecha_inicio else 'Inicio'; f_fin = filtro_fecha_fin.strftime('%d/%m/%Y') if filtro_fecha_fin else 'Fin'; titulo_reporte += f" ({f_inicio} - {f_fin})"
        
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Ventas'); workbook = writer.book; worksheet = writer.sheets['Ventas']
                
                # Dejo el formato comentado, si quieres reintroducirlo, tendrás que añadir una columna más.
                
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment;filename=reporte_ventas.xlsx"})
            
        elif formato == 'pdf':
            # La lógica de PDF también necesita la columna 'Usuario'
            buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
            df_pdf = df.copy(); 
            df_pdf['Cantidad'] = df_pdf['Cantidad'].map('{:,.0f}'.format); 
            df_pdf['Precio Venta'] = df_pdf['Precio Venta'].map('{:,.2f}'.format); 
            df_pdf['Costo Total Est.'] = df_pdf['Costo Total Est.'].map('{:,.2f}'.format); 
            df_pdf['Ganancia Est.'] = df_pdf['Ganancia Est.'].map('{:,.2f}'.format); 
            
            pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); 
            table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
            # Nota: El estilo de la tabla PDF puede necesitar ajustes de ancho si la nueva columna lo rompe.
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'), 
                ('ALIGN', (5, 1), (-2, -1), 'RIGHT') # Ajustado a -2 para incluir la nueva columna
            ]))
            elements.append(table); doc.build(elements); buffer.seek(0)
            return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": f"attachment;filename=reporte_ventas.pdf"})
            
        return redirect(url_for('ventas'))
    except Exception as e:
        app.logger.error(f"Error en exportar_ventas: {e}", exc_info=True)
        flash(f"Error interno al exportar ventas.", "danger")
        return redirect(url_for('ventas'))
    
@app.route('/exportar_movimientos/<string:formato>')
@login_required
def exportar_movimientos(formato):
    try:
        filtro = request.args.get("tipo", "")
        
        # Usar OUTERJOIN y func.coalesce para seguridad
        query = Movimiento.query.outerjoin(User, Movimiento.user_id == User.id).filter_by(tenant_id=current_user.tenant_id)
        
        if filtro:
            query = query.filter(Movimiento.tipo == filtro)
            
        movimientos = query.add_columns(
            Movimiento.fecha, 
            Movimiento.tipo, 
            Movimiento.descripcion, 
            func.coalesce(User.username, '- (Eliminado)').label('username') 
        ).order_by(Movimiento.fecha.desc()).all()
        
        if not movimientos: 
            flash("No hay movimientos para exportar con los filtros aplicados.", "info")
            return redirect(url_for('reportes_y_movimientos'))
        
        # Mapeo de datos para DataFrame - CORRECCIÓN DE FECHA
        data_dict = []
        for m in movimientos:
            fecha_str = m.fecha.strftime('%Y-%m-%d %H:%M:%S') if m.fecha else 'N/A' # Protección contra fecha nula
            data_dict.append({
                'Fecha': fecha_str, 
                'Tipo': m.tipo, 
                'Descripcion': m.descripcion, 
                'Usuario': m.username
            })
        df = pd.DataFrame(data_dict)
        
        titulo_reporte = "Historial de Movimientos"
        if filtro: titulo_reporte += f" (Tipo: {filtro})"
        
        if formato == 'excel':
            output = BytesIO();
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Movimientos')
                workbook = writer.book; worksheet = writer.sheets['Movimientos']
                
                # --- FORMATO COMENTADO PARA DEBUG ---
                # worksheet.set_column('A:A', 18); worksheet.set_column('B:B', 12); worksheet.set_column('C:C', 50); worksheet.set_column('D:D', 20)
                # worksheet.autofilter(0, 0, len(df), len(df.columns) - 1); worksheet.freeze_panes(1, 0)
                # --- FIN FORMATO COMENTADO ---
                
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=historial_movimientos.xlsx"})
            
        elif formato == 'pdf':
            buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch);
            elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)]
            pdf_data = [list(df.columns)] + df.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('GRID', (0, 0), (-1, -1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 8), ('VALIGN', (0,0), (-1,-1), 'TOP')])); elements.append(table); doc.build(elements); buffer.seek(0)
            return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=historial_movimientos.pdf"})
            
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_movimientos: {e}", exc_info=True)
        flash(f"Error interno al exportar movimientos.", "danger")
        return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_stock_bajo/<string:formato>')
@login_required
def exportar_stock_bajo(formato):
    try:
        current_tenant_id = current_user.tenant_id; umbral_configurado = app.config.get('UMBRAL_STOCK_BAJO_GLOBAL', 10)
        query = Stock.query.filter(Stock.tenant_id == current_tenant_id, Stock.cantidad <= umbral_configurado).join(Deposito, Stock.deposito_id == Deposito.id).options(db.joinedload(Stock.deposito_ref))
        filtro_deposito_id = request.args.get("deposito_id", "", type=int); filtro_categoria = request.args.get("categoria_nombre", "")
        if filtro_deposito_id: query = query.filter(Stock.deposito_id == filtro_deposito_id)
        if filtro_categoria: query = query.filter(Stock.categoria == filtro_categoria)
        stocks_bajos = query.order_by(Stock.cantidad, Deposito.nombre_deposito, Stock.producto).all()
        if not stocks_bajos: flash("No hay productos con stock bajo o agotado según los filtros.", "info"); return redirect(url_for('reportes_y_movimientos'))
        data_list = []
        for s in stocks_bajos:
            estado = "Agotado" if s.cantidad == 0 else "Bajo"; data_list.append({'Producto': s.producto, 'Categoria': s.categoria if s.categoria else '-', 'Deposito': s.deposito_ref.nombre_deposito, 'Cantidad Actual': s.cantidad, 'Unidad': s.unidad, 'Estado': estado})
        titulo_reporte = "Reporte de Stock Bajo / Agotado"; df = pd.DataFrame(data_list); df = df[['Producto', 'Categoria', 'Deposito', 'Cantidad Actual', 'Unidad', 'Estado']]
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Stock Bajo')
                workbook = writer.book; worksheet = writer.sheets['Stock Bajo']
                
                # --- FORMATO COMENTADO PARA DEBUG ---
                # number_format = workbook.add_format({'num_format': '#,##0'})
                # agotado_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                # worksheet.conditional_format('F2:F{}'.format(len(df)+1), {'type': 'cell', 'criteria': '==', 'value': '"Agotado"', 'format': agotado_format})
                # worksheet.set_column('A:C', 20); worksheet.set_column('D:D', 15, number_format); worksheet.set_column('E:F', 12); worksheet.autofilter(0, 0, len(df), len(df.columns) - 1); worksheet.freeze_panes(1, 0)
                # --- FIN FORMATO COMENTADO ---
                
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_stock_bajo.xlsx"})
        elif formato == 'pdf':
             buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=letter); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
             df_pdf = df.copy(); df_pdf['Cantidad Actual'] = df_pdf['Cantidad Actual'].map('{:,.0f}'.format); pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
             table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9), ('ALIGN', (3,1), (3,-1), 'RIGHT')])); elements.append(table); doc.build(elements); buffer.seek(0)
             return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_stock_bajo.pdf"})
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_stock_bajo: {e}", exc_info=True)
        flash(f"Error interno al exportar stock bajo.", "danger")
        return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_ventas_categoria/<string:formato>')
@login_required
def exportar_ventas_categoria(formato):
    try:
        current_tenant_id = current_user.tenant_id; filtro_fecha_inicio_str = request.args.get("fecha_inicio", ""); filtro_fecha_fin_str = request.args.get("fecha_fin", ""); filtro_deposito_id = request.args.get("deposito_id", "", type=int); filtro_fecha_inicio = None
        if filtro_fecha_inicio_str: 
            try: filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio_str, '%Y-%m-%d') 
            except ValueError: pass
        filtro_fecha_fin = None;
        if filtro_fecha_fin_str: 
            try: filtro_fecha_fin = datetime.strptime(filtro_fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) 
            except ValueError: pass
        query = db.session.query(Stock.categoria, Venta.moneda, func.sum(Venta.cantidad).label('total_cantidad'), func.sum(Venta.precio_venta).label('total_valor'), func.count(Venta.id).label('num_ventas')).join(Stock, (Venta.producto == Stock.producto) & (Venta.tenant_id == Stock.tenant_id)).filter(Venta.tenant_id == current_user.tenant_id)
        if filtro_fecha_inicio: query = query.filter(Venta.fecha >= filtro_fecha_inicio)
        if filtro_fecha_fin: query = query.filter(Venta.fecha <= filtro_fecha_fin)
        if filtro_deposito_id: query = query.filter(Stock.deposito_id == filtro_deposito_id)
        results = query.group_by(Stock.categoria, Venta.moneda).order_by(Stock.categoria, Venta.moneda).all()
        if not results: flash("No se encontraron ventas por categoría con los filtros aplicados.", "info"); return redirect(url_for('reportes_y_movimientos'))
        data_list = []
        for r in results:
            categoria = r.categoria if r.categoria else "Sin Categoría"; valor_promedio = float(r.total_valor / r.num_ventas) if r.num_ventas > 0 and r.total_valor is not None else 0.0
            data_list.append({'Categoria': categoria, 'Moneda': r.moneda, 'Cantidad Vendida': r.total_cantidad, 'Valor Total Ventas': r.total_valor, 'Número de Ventas': r.num_ventas, 'Valor Promedio Venta': valor_promedio})
        titulo_reporte = "Análisis de Ventas por Categoría"; df = pd.DataFrame(data_list)
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Ventas x Cat')
                workbook = writer.book; worksheet = writer.sheets['Ventas x Cat']
                
                # --- FORMATO COMENTADO PARA DEBUG ---
                # money_format = workbook.add_format({'num_format': '$#,##0.00'}); number_format = workbook.add_format({'num_format': '#,##0'})
                # worksheet.set_column('A:A', 25); worksheet.set_column('B:B', 8); worksheet.set_column('C:C', 18, number_format); worksheet.set_column('D:D', 20, money_format); worksheet.set_column('E:E', 18, number_format); worksheet.set_column('F:F', 20, money_format)
                # worksheet.autofilter(0, 0, len(df), len(df.columns) - 1); worksheet.freeze_panes(1, 0)
                # --- FIN FORMATO COMENTADO ---

            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_ventas_categoria.xlsx"})
        elif formato == 'pdf':
            buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=letter); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
            df_pdf = df.copy(); df_pdf['Cantidad Vendida'] = df_pdf['Cantidad Vendida'].map('{:,.0f}'.format); df_pdf['Valor Total Ventas'] = df_pdf['Valor Total Ventas'].map('{:,.2f}'.format); df_pdf['Número de Ventas'] = df_pdf['Número de Ventas'].map('{:,.0f}'.format); df_pdf['Valor Promedio Venta'] = df_pdf['Valor Promedio Venta'].map('{:,.2f}'.format)
            pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9), ('ALIGN', (2,1), (-1,-1), 'RIGHT')])); elements.append(table); doc.build(elements); buffer.seek(0)
            return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_ventas_categoria.pdf"})
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_ventas_categoria: {e}", exc_info=True)
        flash(f"Error interno al exportar ventas por categoría.", "danger")
        return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_stock_deposito/<int:deposito_id>/<string:formato>')
@login_required
def exportar_stock_deposito(deposito_id, formato):
    try:
        current_tenant_id = current_user.tenant_id; deposito = Deposito.query.filter_by(id=deposito_id, tenant_id=current_tenant_id).first_or_404()
        stocks_export = Stock.query.filter_by(tenant_id=current_tenant_id, deposito_id=deposito_id).order_by(Stock.categoria, Stock.producto).all()
        if not stocks_export: flash(f"No hay stock registrado en el depósito '{deposito.nombre_deposito}'.", "info"); return redirect(url_for('depositos'))
        data_list = []
        for s in stocks_export:
            costo_unitario = float(s.precio_compra / s.cantidad) if s.cantidad > 0 and s.precio_compra is not None else 0.0; valor_total = s.precio_compra if s.precio_compra is not None else 0.0
            data_list.append({'Producto': s.producto, 'Categoria': s.categoria if s.categoria else '-', 'Cantidad': s.cantidad, 'Unidad': s.unidad, 'Moneda': s.moneda, 'Precio Compra (Total Lote)': valor_total, 'Costo Unitario Est.': costo_unitario, 'Valor Total Est.': valor_total})
        titulo_reporte = f"Reporte de Stock - Depósito: {deposito.nombre_deposito}"; df = pd.DataFrame(data_list); df = df[['Producto', 'Categoria', 'Cantidad', 'Unidad', 'Moneda', 'Precio Compra (Total Lote)', 'Costo Unitario Est.', 'Valor Total Est.']]
        filename_base = f"reporte_stock_{deposito.nombre_deposito.replace(' ', '_')}"
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name=deposito.nombre_deposito[:30])
                workbook = writer.book; worksheet = writer.sheets[deposito.nombre_deposito[:30]]
               
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment;filename={filename_base}.xlsx"})
        elif formato == 'pdf':
            buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
            df_pdf = df.copy(); df_pdf['Cantidad'] = df_pdf['Cantidad'].map('{:,.0f}'.format); df_pdf['Precio Compra (Total Lote)'] = df_pdf['Precio Compra (Total Lote)'].map('{:,.2f}'.format); df_pdf['Costo Unitario Est.'] = df_pdf['Costo Unitario Est.'].map('{:,.2f}'.format); df_pdf['Valor Total Est.'] = df_pdf['Valor Total Est.'].map('{:,.2f}'.format)
            pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
            table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black),('FONTSIZE', (0, 0), (-1, -1), 8), ('ALIGN', (2, 1), (-1, -1), 'RIGHT')])); elements.append(table); doc.build(elements); buffer.seek(0)
            return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": f"attachment;filename={filename_base}.pdf"})
        return redirect(url_for('depositos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_stock_deposito: {e}", exc_info=True)
        flash(f"Error interno al exportar stock de depósito.", "danger")
        return redirect(url_for('depositos'))

@app.route('/exportar_ingresos_stock/<string:formato>')
@login_required
def exportar_ingresos_stock(formato):
    try:
        current_tenant_id = current_user.tenant_id; filtro_fecha_inicio_str = request.args.get("fecha_inicio", ""); filtro_fecha_fin_str = request.args.get("fecha_fin", ""); filtro_producto_nombre = request.args.get("producto_nombre", ""); filtro_categoria_nombre = request.args.get("categoria_nombre", ""); filtro_deposito_id = request.args.get("deposito_id", "", type=int); filtro_user_id = request.args.get("user_id", "", type=int); filtro_fecha_inicio = None
        if filtro_fecha_inicio_str: 
            try: filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio_str, '%Y-%m-%d') 
            except ValueError: pass
        filtro_fecha_fin = None;
        if filtro_fecha_fin_str: 
            try: filtro_fecha_fin = datetime.strptime(filtro_fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) 
            except ValueError: pass
        query = db.session.query(Movimiento.fecha, Movimiento.descripcion, Stock.producto, Stock.categoria, Deposito.nombre_deposito, User.username).join(User, Movimiento.user_id == User.id).outerjoin(Stock, (Movimiento.descripcion.like('%' + Stock.producto + '%')) & (Stock.tenant_id == Movimiento.tenant_id)).outerjoin(Deposito, Stock.deposito_id == Deposito.id).filter(Movimiento.tenant_id == current_user.tenant_id).filter(Movimiento.tipo == 'STOCK').filter(db.or_(Movimiento.descripcion.like('Agregado:%'), Movimiento.descripcion.like('Importación:%'), Movimiento.descripcion.like('Ajuste:%'), Movimiento.descripcion.like('%restaurado%')))
        if filtro_fecha_inicio: query = query.filter(Movimiento.fecha >= filtro_fecha_inicio)
        if filtro_fecha_fin: query = query.filter(Movimiento.fecha <= filtro_fecha_fin)
        if filtro_producto_nombre: query = query.filter(Stock.producto == filtro_producto_nombre)
        if filtro_categoria_nombre: query = query.filter(Stock.categoria == filtro_categoria_nombre)
        if filtro_deposito_id: query = query.filter(Stock.deposito_id == filtro_deposito_id)
        if filtro_user_id: query = query.filter(Movimiento.user_id == filtro_user_id)
        ingresos = query.order_by(Movimiento.fecha.desc()).all()
        if not ingresos: flash("No se encontraron ingresos de stock con los filtros.", "info"); return redirect(url_for('reportes_y_movimientos'))
        data_list = [{'Fecha': i.fecha.strftime('%Y-%m-%d %H:%M'), 'Descripción Movimiento': i.descripcion, 'Producto Asociado': i.producto if i.producto else '-', 'Categoría': i.categoria if i.categoria else '-', 'Depósito': i.nombre_deposito if i.nombre_deposito else '-', 'Usuario': i.username} for i in ingresos]
        titulo_reporte = "Reporte de Ingresos de Stock"; df = pd.DataFrame(data_list)
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Ingresos Stock')
                workbook = writer.book; worksheet = writer.sheets['Ingresos Stock']
            
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_ingresos_stock.xlsx"})
        elif formato == 'pdf':
             buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch);
             elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)]
             pdf_data = [list(df.columns)] + df.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
             table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('GRID', (0, 0), (-1, -1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 8), ('VALIGN', (0,0), (-1,-1), 'TOP')])); elements.append(table); doc.build(elements);
             buffer.seek(0); return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_ingresos_stock.pdf"})
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_ingresos_stock: {e}", exc_info=True)
        flash(f"Error interno al exportar ingresos de stock.", "danger")
        return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_resumen_depositos/<string:formato>')
@login_required
def exportar_resumen_depositos(formato):
    try:
        current_tenant_id = current_user.tenant_id
        results = db.session.query(Deposito.id, Deposito.nombre_deposito, Deposito.ubicacion, Deposito.telefono, Deposito.email, Deposito.comentarios, func.count(Stock.id).label('num_productos')).outerjoin(Stock, Deposito.id == Stock.deposito_id).filter(Deposito.tenant_id == current_user.tenant_id).group_by(Deposito.id).order_by(Deposito.nombre_deposito).all()
        depositos_data = []
        for d_id, d_nombre, d_ubicacion, d_telefono, d_email, d_comentarios, d_num_prod in results:
            valor_deposito = {'USD': 0.0, '$': 0.0}; stocks_en_deposito = Stock.query.filter_by(deposito_id=d_id).all()
            for s in stocks_en_deposito:
                # CORRECCIÓN: Asegurar que precio_compra no sea None antes de sumar
                if s.moneda in valor_deposito and s.precio_compra is not None: valor_deposito[s.moneda] += s.precio_compra
                
            depositos_data.append({'Depósito': d_nombre, 'Ubicación': d_ubicacion, 'Teléfono': d_telefono, 'Email': d_email, 'Comentarios': d_comentarios, '# Productos': d_num_prod, 'Valor Total Est. (USD)': valor_deposito['USD'], 'Valor Total Est. ($)': valor_deposito['$']})
        if not depositos_data: flash("No hay depósitos registrados.", "info"); return redirect(url_for('reportes_y_movimientos'))
        titulo_reporte = "Resumen de Depósitos"; df = pd.DataFrame(depositos_data)
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Resumen Depósitos')
                workbook = writer.book; worksheet = writer.sheets['Resumen Depósitos']
            
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_resumen_depositos.xlsx"})
        elif formato == 'pdf':
             buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
             df_pdf = df.copy(); df_pdf['# Productos'] = df_pdf['# Productos'].map('{:,.0f}'.format); df_pdf['Valor Total Est. (USD)'] = df_pdf['Valor Total Est. (USD)'].map('{:,.2f}'.format); df_pdf['Valor Total Est. ($)'] = df_pdf['Valor Total Est. ($)'].map('{:,.2f}'.format)
             pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
             table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black),('FONTSIZE', (0,0), (-1,-1), 8), ('VALIGN',(0,0),(-1,-1),'TOP'), ('ALIGN', (5,1), (-1,-1), 'RIGHT')])); elements.append(table); doc.build(elements);
             buffer.seek(0); return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_resumen_depositos.pdf"})
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_resumen_depositos: {e}", exc_info=True)
        flash(f"Error interno al exportar resumen de depósitos.", "danger")
        return redirect(url_for('reportes_y_movimientos'))

@app.route('/exportar_actividad_usuarios/<string:formato>')
@login_required
def exportar_actividad_usuarios(formato):
    try:
        current_tenant_id = current_user.tenant_id; filtro_fecha_inicio_str = request.args.get("fecha_inicio", ""); filtro_fecha_fin_str = request.args.get("fecha_fin", ""); filtro_user_id = request.args.get("user_id", "", type=int); filtro_fecha_inicio = None
        if filtro_fecha_inicio_str: 
            try: filtro_fecha_inicio = datetime.strptime(filtro_fecha_inicio_str, '%Y-%m-%d') 
            except ValueError: pass
        filtro_fecha_fin = None;
        if filtro_fecha_fin_str: 
            try: filtro_fecha_fin = datetime.strptime(filtro_fecha_fin_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) 
            except ValueError: pass
        query_users = User.query.filter_by(tenant_id=current_user.tenant_id);
        if filtro_user_id: query_users = query_users.filter(User.id == filtro_user_id)
        users = query_users.order_by(User.username).all()
        user_activity = []
        for user in users:
            q_ventas = db.session.query(func.count(Venta.id), func.sum(Venta.precio_venta), Venta.moneda).filter(Venta.user_id == user.id)
            if filtro_fecha_inicio: q_ventas = q_ventas.filter(Venta.fecha >= filtro_fecha_inicio)
            if filtro_fecha_fin: q_ventas = q_ventas.filter(Venta.fecha <= filtro_fecha_fin)
            ventas_res = q_ventas.group_by(Venta.moneda).all(); num_ventas = sum(v[0] for v in ventas_res); total_ventas_str = ", ".join([f"{v[2]} {v[1]:,.2f}" for v in ventas_res if v[1] is not None]) if ventas_res else "-"
            q_mov = db.session.query(func.count(Movimiento.id)).filter(Movimiento.user_id == user.id)
            if filtro_fecha_inicio: q_mov = q_mov.filter(Movimiento.fecha >= filtro_fecha_inicio)
            if filtro_fecha_fin: q_mov = q_mov.filter(Movimiento.fecha <= filtro_fecha_fin)
            num_movimientos = q_mov.scalar() or 0
            user_activity.append({'Usuario': user.username, '# Ventas Registradas': num_ventas, 'Valor Total Ventas': total_ventas_str, '# Movimientos Stock/Depósito': num_movimientos})
        if not user_activity: flash("No se encontró actividad de usuarios con los filtros aplicados.", "info"); return redirect(url_for('reportes_y_movimientos'))
        titulo_reporte = "Reporte de Actividad de Usuarios"; df = pd.DataFrame(user_activity); df = df[['Usuario', '# Ventas Registradas', 'Valor Total Ventas', '# Movimientos Stock/Depósito']]
        if formato == 'excel':
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Actividad Usuarios')
                workbook = writer.book; worksheet = writer.sheets['Actividad Usuarios']
            
            output.seek(0); return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment;filename=reporte_actividad_usuarios.xlsx"})
        elif formato == 'pdf':
             buffer = BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=letter); elements = [Paragraph(titulo_reporte, getSampleStyleSheet()['h1']), Spacer(1, 0.2*inch)];
             df_pdf = df.copy(); df_pdf['# Ventas Registradas'] = df_pdf['# Ventas Registradas'].map('{:,.0f}'.format); df_pdf['# Movimientos Stock/Depósito'] = df_pdf['# Movimientos Stock/Depósito'].map('{:,.0f}'.format)
             pdf_data = [df_pdf.columns.values.tolist()] + df_pdf.values.tolist(); table = Table(pdf_data, hAlign='LEFT', repeatRows=1)
             table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#198754')),('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),('GRID', (0, 0), (-1, -1), 1, colors.black), ('FONTSIZE', (0,0), (-1,-1), 9), ('ALIGN', (1,1), (1,-1), 'RIGHT'), ('ALIGN', (3,1), (3,-1), 'RIGHT')])); elements.append(table); doc.build(elements);
             buffer.seek(0); return Response(buffer, mimetype="application/pdf", headers={"Content-Disposition": "attachment;filename=reporte_actividad_usuarios.pdf"})
        return redirect(url_for('reportes_y_movimientos'))
    except Exception as e:
        app.logger.error(f"Error en exportar_actividad_usuarios: {e}", exc_info=True)
        flash(f"Error interno al exportar actividad de usuarios.", "danger")
        return redirect(url_for('reportes_y_movimientos'))


@app.route('/generar_reporte_modal', methods=['POST'])
@login_required
def generar_reporte_modal():
     try:
        current_tenant_id = current_user.tenant_id; reporte_tipo = request.form.get('reporte_tipo'); formato = request.form.get('formato')
        fecha_inicio_str = request.form.get('fecha_inicio', ""); fecha_fin_str = request.form.get('fecha_fin', ""); deposito_id = request.form.get('deposito_id', "", type=int); producto_nombre = request.form.get('producto_nombre', ""); categoria_nombre = request.form.get('categoria_nombre', ""); user_id_filtro = request.form.get('user_id', "", type=int)
        export_args = {'formato': formato, 'fecha_inicio': fecha_inicio_str, 'fecha_fin': fecha_fin_str, 'deposito_id': deposito_id, 'producto_nombre': producto_nombre, 'categoria_nombre': categoria_nombre, 'user_id': user_id_filtro}
        export_args = {k: v for k, v in export_args.items() if v}
        endpoint_map = {
            'valor_inventario': 'exportar_stock',
            'valor_por_deposito': 'exportar_resumen_depositos',
            'stock_bajo': 'exportar_stock_bajo',
            'ingresos_stock': 'exportar_ingresos_stock',
            'resumen_depositos': 'exportar_resumen_depositos',
            'ventas_periodo': 'exportar_ventas',
            'rentabilidad_ventas': 'exportar_ventas',
            'ventas_por_usuario': 'exportar_actividad_usuarios',
            'historial_producto': None,
            'ventas_categoria': 'exportar_ventas_categoria',
            'actividad_usuarios': 'exportar_actividad_usuarios'
        }
        endpoint = endpoint_map.get(reporte_tipo)
        if endpoint:
            if reporte_tipo == 'valor_inventario':
                 export_args['deposito'] = export_args.pop('deposito_id', None); export_args['categoria'] = export_args.pop('categoria_nombre', None); export_args = {k: v for k, v in export_args.items() if v is not None}
            elif reporte_tipo in ['ventas_periodo', 'rentabilidad_ventas']:
                if 'producto_nombre' in export_args and export_args['producto_nombre']: stock_obj = Stock.query.filter_by(tenant_id=current_user.tenant_id, producto=export_args['producto_nombre']).first(); export_args['producto'] = stock_obj.id if stock_obj else None
                export_args.pop('producto_nombre', None); export_args.pop('categoria_nombre', None); export_args.pop('user_id', None); export_args = {k: v for k, v in export_args.items() if v is not None}
            elif reporte_tipo == 'ventas_por_usuario':
                 export_args.pop('deposito_id', None); export_args.pop('producto_nombre', None); export_args.pop('categoria_nombre', None); export_args = {k: v for k, v in export_args.items() if v is not None}

            if reporte_tipo == 'historial_producto':
                 flash(f"Reporte '{reporte_tipo.replace('_', ' ').title()}' aún no implementado.", "info"); return redirect(url_for('reportes_y_movimientos'))

            return redirect(url_for(endpoint, **export_args))
        else:
             flash(f"Exportación directa para el reporte '{reporte_tipo.replace('_', ' ').title()}' no implementada.", "info"); return redirect(url_for('reportes_y_movimientos'))
     except Exception as e: flash(f"Error generando reporte: {e}", "danger"); app.logger.error(f"Error en generar_reporte_modal: {e}", exc_info=True); return redirect(url_for('reportes_y_movimientos'))


def generar_notificaciones():
    if not current_user.is_authenticated or current_user.role == 'admin': return
    current_tenant_id = current_user.tenant_id; umbral_configurado = app.config.get('UMBRAL_STOCK_BAJO_GLOBAL', 10); hace_24_horas = datetime.utcnow() - timedelta(hours=24)
    items_bajos = Stock.query.filter(Stock.tenant_id == current_tenant_id, Stock.cantidad > 0, Stock.cantidad <= umbral_configurado).all()
    
    for item in items_bajos:
        notif_existente = Notificacion.query.filter_by(
            titulo=f"Stock Bajo: {item.producto}", 
            tenant_id=current_tenant_id,
            link=f"/stocks?deposito={item.deposito_id}" # Añadir filtro por depósito a la notificación
        ).order_by(Notificacion.fecha.desc()).first()
        
        mensaje = f"Quedan {item.cantidad} {item.unidad} en '{item.deposito_ref.nombre_deposito}'. (Umbral: {umbral_configurado})"
        link_url = f"/stocks?deposito={item.deposito_id}" # Definir URL de enlace
        
        if not notif_existente: 
            db.session.add(Notificacion(tipo='warning', titulo=f"Stock Bajo: {item.producto}", mensaje=mensaje, tenant_id=current_tenant_id, link=link_url))
        elif notif_existente.leido and notif_existente.fecha < hace_24_horas: 
            notif_existente.leido = False; notif_existente.fecha = datetime.utcnow(); notif_existente.mensaje = mensaje

    items_agotados = Stock.query.filter(Stock.tenant_id==current_tenant_id, Stock.cantidad == 0).all()
    for item in items_agotados:
        notif_existente = Notificacion.query.filter_by(
            titulo=f"Stock Agotado: {item.producto}", 
            tenant_id=current_tenant_id,
            link=f"/stocks?deposito={item.deposito_id}"
        ).order_by(Notificacion.fecha.desc()).first()
        
        mensaje_agotado = f"Producto agotado en '{item.deposito_ref.nombre_deposito}'."
        link_url = f"/stocks?deposito={item.deposito_id}"
        
        if not notif_existente: 
            db.session.add(Notificacion(tipo='danger', titulo=f"Stock Agotado: {item.producto}", mensaje=mensaje_agotado, tenant_id=current_tenant_id, link=link_url))
        elif notif_existente.leido and notif_existente.fecha < hace_24_horas: 
            notif_existente.leido = False; notif_existente.fecha = datetime.utcnow(); notif_existente.mensaje = mensaje_agotado
    
    if db.session.new or db.session.dirty: 
        try: db.session.commit() 
        except Exception as e: db.session.rollback(); print(f"Error commit notif: {e}")

@app.context_processor
def inject_notifications():
    if not current_user.is_authenticated: return dict(unread_notification_count=0, notifications_for_dropdown=[])
    conteo = 0; notificaciones = [];
    if current_user.role == 'admin': notif_query = Notificacion.query.filter(Notificacion.tenant_id.is_(None), Notificacion.leido == False)
    else: generar_notificaciones(); notif_query = Notificacion.query.filter_by(tenant_id=current_user.tenant_id, leido=False)
    conteo = notif_query.count(); notificaciones = notif_query.order_by(Notificacion.fecha.desc()).limit(5).all()
    return dict(unread_notification_count=conteo, notifications_for_dropdown=notificaciones)

@app.route("/notificaciones/marcar-leidas")
@login_required
def marcar_leidas():
    try:
        query_filter = Notificacion.tenant_id.is_(None) if current_user.role == 'admin' else Notificacion.tenant_id == current_user.tenant_id
        Notificacion.query.filter(query_filter, Notificacion.leido == False).update({Notificacion.leido: True, Notificacion.fecha: datetime.utcnow()}, synchronize_session=False); db.session.commit(); flash("Notificaciones leídas.", "success")
    except Exception as e: db.session.rollback(); flash(f"Error: {e}", "danger")
    return redirect(request.referrer or url_for('home'))

@app.route("/notificaciones/todas")
@login_required
def todas_las_notificaciones():
     if current_user.role == 'admin': query = Notificacion.query.filter(Notificacion.tenant_id.is_(None))
     else: query = Notificacion.query.filter_by(tenant_id=current_user.tenant_id)
     todas = query.order_by(Notificacion.leido.asc(), Notificacion.fecha.desc()).all(); return render_template("todas_las_notificaciones.html", notificaciones=todas)


@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    total_tenants = db.session.query(func.count(Tenant.id)).filter(Tenant.id != 'GLOBAL').scalar(); total_users = db.session.query(func.count(User.id)).filter(User.role != 'admin').scalar(); total_stocks = db.session.query(func.count(Stock.id)).scalar(); total_ventas = db.session.query(func.count(Venta.id)).scalar()
    stats = {'total_tenants': total_tenants, 'total_users': total_users, 'total_stocks': total_stocks, 'total_ventas': total_ventas}
    tenants_info_query = db.session.query(Tenant.id, Tenant.plan, func.count(User.id).label('user_count')).outerjoin(User, Tenant.id == User.tenant_id).filter(Tenant.id != 'GLOBAL').group_by(Tenant.id).order_by(Tenant.id).all(); tenants_info = []
    for id, plan_name, user_count in tenants_info_query:
        temp_tenant = Tenant(id=id, plan=plan_name); tenants_info.append({'id': id, 'plan': plan_name, 'user_limit': temp_tenant.user_limit, 'stock_limit': temp_tenant.stock_limit, 'deposito_limit': temp_tenant.deposito_limit, 'user_count': user_count})
    users = User.query.filter(User.role != 'admin').order_by(User.tenant_id, User.username).all(); available_plans = list(PLAN_LIMITS.keys())
    return render_template('admin.html', users=users, tenants_info=tenants_info, stats=stats, available_plans=available_plans, PLAN_LIMITS=PLAN_LIMITS)

@app.route('/admin/send-reset-email/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin': return jsonify({'success': False, 'message': 'No se puede resetear la contraseña del administrador.'}), 403
    if send_password_reset_email(user): return jsonify({'success': True, 'message': f'Email de reseteo enviado correctamente a {user.email}.'})
    else: return jsonify({'success': False, 'message': f'Error al intentar enviar email de reseteo a {user.email}.'}), 500

@app.route('/admin/resend-confirmation/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def resend_confirmation(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin': return jsonify({'success': False, 'message': 'El administrador ya está confirmado.'}), 400
    if user.email_confirmed: return jsonify({'success': False, 'message': f'El email {user.email} ya está confirmado.'}), 400
    if send_confirmation_email(user): return jsonify({'success': True, 'message': f'Email de confirmación reenviado a {user.email}.'})
    else: return jsonify({'success': False, 'message': f'Error al intentar reenviar email de confirmación a {user.email}.'}), 500

@app.route('/admin/delete-user/<int:user_id>')
@login_required
@admin_required
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.role == 'admin': flash('No eliminar admin.', 'danger'); return redirect(url_for('admin_panel'))
    try:
        username_eliminado = user_to_delete.username; db.session.delete(user_to_delete); db.session.commit(); flash(f'Usuario {username_eliminado} eliminado.', 'success')
    except Exception as e: db.session.rollback(); flash(f'Error: {e}', "danger")
    return redirect(url_for('admin_panel'))


@app.cli.command("create-tables")
def create_tables():
    try:
        with app.app_context(): print("INFO: Ejecutando db.create_all() desde comando CLI..."); db.create_all()
        print("INFO: Comando create-tables finalizado con éxito.")
    except Exception as e: print(f"ERROR en comando create-tables: {e}")

@app.cli.command("create-admin")
def create_admin():
    try:
        with app.app_context():
            admin_username = 'admin'; admin_tenant_id = 'GLOBAL'
            existing_admin = User.query.filter_by(username=admin_username).first()
            if existing_admin: print(f"INFO: El usuario '{admin_username}' ya existe."); return
            print(f"INFO: Creando usuario '{admin_username}'...")
            global_tenant = Tenant.query.get(admin_tenant_id)
            if not global_tenant:
                print(f"INFO: Creando tenant '{admin_tenant_id}'..."); global_tenant = Tenant(id=admin_tenant_id, plan='Enterprise'); db.session.add(global_tenant); db.session.commit(); print(f"INFO: Tenant '{admin_tenant_id}' creado.")
            hashed_pw = bcrypt.generate_password_hash('admin').decode('utf-8')
            admin_user = User(username=admin_username, password=hashed_pw, tenant_id=admin_tenant_id, dni='0', email='admin@elsilo.local', role='admin', email_confirmed=True)
            db.session.add(admin_user); db.session.commit(); print(f"INFO: Usuario '{admin_username}' creado con éxito.")
    except Exception as e: db.session.rollback(); print(f"ERROR en comando create-admin: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)