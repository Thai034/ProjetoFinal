from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
import mysql.connector
import json
from datetime import datetime
import os
from typing import Dict, List, Optional
import hashlib
import secrets

# Atualizar o caminho para os templates e arquivos estáticos
app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static"
)
app.secret_key = os.environ.get('SECRET_KEY', 'sua_chave_secreta_muito_segura_aqui_ecotrace_2025')
CORS(app)

# Configuração do Aiven MySQL
MYSQL_CONFIG = {
    'host': os.environ.get('AIVEN_HOST'),
    'user': os.environ.get('AIVEN_USER'),
    'password': os.environ.get('AIVEN_PASSWORD'),
    'database': os.environ.get('AIVEN_DB'),
    'port': int(os.environ.get('AIVEN_PORT')),
    'connect_timeout': int(os.environ.get('AIVEN_TIMEOUT', '10')),
}

# Caminho temporário para o certificado CA
_SSL_CA_PATH = None
_DB_INITIALIZED = False

# Função para conectar ao MySQL
def get_db_connection(use_database=True):
    global _SSL_CA_PATH
    try:
        conn_params = dict(MYSQL_CONFIG)
        
        # Remover database se não for usar
        if not use_database:
            conn_params.pop('database', None)

        # Suporte a certificado CA
        ssl_ca_env = os.environ.get('AIVEN_SSL_CA') or os.environ.get('MYSQL_SSL_CA')
        if ssl_ca_env:
            if _SSL_CA_PATH is None:
                import tempfile, base64
                pem_data = ssl_ca_env
                if '-----BEGIN CERTIFICATE-----' not in pem_data:
                    try:
                        pem_data = base64.b64decode(ssl_ca_env).decode('utf-8')
                    except Exception:
                        pem_data = ssl_ca_env
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pem')
                tmp.write(pem_data.encode('utf-8'))
                tmp.flush()
                tmp.close()
                _SSL_CA_PATH = tmp.name
            conn_params['ssl_ca'] = _SSL_CA_PATH
            conn_params['ssl_verify_cert'] = True
        else:
            conn_params.pop('ssl_ca', None)
            conn_params.pop('ssl_verify_cert', None)

        conn = mysql.connector.connect(**conn_params)
        return conn
    except mysql.connector.Error as e:
        print(f"❌ Erro ao conectar com MySQL: {e}")
        return None

# Sistema de hash de senha
def hash_password(password):
    salt = "ecotrace_salt_2025_cop30"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

# Função para inicializar banco de dados (com tratamento de erros melhorado)
def init_db():
    global _DB_INITIALIZED
    
    if _DB_INITIALIZED:
        return True
    
    try:
        print("🔄 Verificando/criando banco de dados...")
        
        # Conectar sem especificar database
        conn = get_db_connection(use_database=False)
        if not conn:
            print("❌ Não foi possível conectar ao MySQL")
            return False
            
        cursor = conn.cursor()

        # Criar banco de dados se não existir
        database_name = MYSQL_CONFIG['database']
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}`")
        print(f"✅ Banco de dados '{database_name}' verificado/criado")

        # Usar o banco de dados
        cursor.execute(f"USE `{database_name}`")

        # Criar tabela de usuários
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                senha VARCHAR(255) NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_email (email)
            )
        ''')
        print("✅ Tabela 'usuarios' verificada/criada")

        # Criar tabela de emissões
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emissions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT,
                quantity DECIMAL(15,2) NOT NULL,
                unit VARCHAR(50) NOT NULL,
                scope VARCHAR(50) NOT NULL,
                emissions_kg DECIMAL(15,2) NOT NULL,
                emissions_tons DECIMAL(15,4) NOT NULL,
                timestamp VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE,
                INDEX idx_user_id (user_id)
            )
        ''')
        print("✅ Tabela 'emissions' verificada/criada")

        conn.commit()
        conn.close()
        
        _DB_INITIALIZED = True
        print("✅ Banco de dados inicializado com sucesso!")
        return True
        
    except mysql.connector.Error as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")
        if conn:
            conn.close()
        return False
    except Exception as e:
        print(f"❌ Erro inesperado ao inicializar banco: {e}")
        if conn:
            conn.close()
        return False

# Middleware para garantir que o DB está inicializado
@app.before_request
def ensure_db_initialized():
    global _DB_INITIALIZED
    if not _DB_INITIALIZED:
        init_db()

# Fatores de emissão
class CarbonCalculator:
    def __init__(self):
        self.emission_factors = {
            'energy': {
                'grid_brazil': 0.082,
                'grid_world': 0.475,
                'coal': 0.950,
                'natural_gas': 0.469,
                'solar': 0.045,
                'wind': 0.011,
                'hydro': 0.024
            },
            'transport': {
                'gasoline_car': 0.192,
                'diesel_car': 0.171,
                'electric_car': 0.053,
                'bus': 0.089,
                'truck': 0.215,
                'airplane': 0.285
            },
            'materials': {
                'steel': 2.30,
                'aluminum': 8.10,
                'cement': 0.93,
                'plastic': 2.53,
                'paper': 1.07,
                'wood': 0.45
            },
            'waste': {
                'landfill': 0.350,
                'incineration': 0.850,
                'recycling': -0.500,
                'composting': 0.120
            },
            'water': {
                'treatment': 0.320,
                'distribution': 0.180,
                'wastewater': 0.450
            }
        }
    
    def calculate_emissions(self, category: str, quantity: float, unit: str, 
                          subcategory: str = None, scope: str = 'direct') -> Dict:
        converted_quantity = self._convert_units(quantity, unit, category)
        
        if category == 'energy':
            emissions = self._calculate_energy_emissions(converted_quantity, subcategory)
        elif category == 'transport':
            emissions = self._calculate_transport_emissions(converted_quantity, subcategory)
        elif category == 'materials':
            emissions = self._calculate_materials_emissions(converted_quantity, subcategory)
        elif category == 'waste':
            emissions = self._calculate_waste_emissions(converted_quantity, subcategory)
        elif category == 'water':
            emissions = self._calculate_water_emissions(converted_quantity, subcategory)
        else:
            emissions = converted_quantity * 1.0
        
        scope_multipliers = {
            'direct': 1.0,
            'indirect': 0.85,  
            'other': 0.75
        }
        
        adjusted_emissions = emissions * scope_multipliers.get(scope, 1.0)
        
        return {
            'category': category,
            'subcategory': subcategory,
            'quantity': quantity,
            'unit': unit,
            'scope': scope,
            'emissions_kg': round(adjusted_emissions, 2),
            'emissions_tons': round(adjusted_emissions / 1000, 4),
            'timestamp': datetime.now().isoformat()
        }
    
    def _convert_units(self, quantity: float, unit: str, category: str) -> float:
        conversions = {
            'energy': {'kwh': 1.0},
            'transport': {'km': 1.0},
            'materials': {'kg': 1.0, 'ton': 1000.0},
            'waste': {'kg': 1.0, 'ton': 1000.0},
            'water': {'m3': 1.0, 'liter': 0.001}
        }
        
        category_conversions = conversions.get(category, {})
        conversion_factor = category_conversions.get(unit, 1.0)
        return quantity * conversion_factor
    
    def _calculate_energy_emissions(self, kwh: float, subcategory: str) -> float:
        if subcategory in self.emission_factors['energy']:
            factor = self.emission_factors['energy'][subcategory]
        else:
            factor = self.emission_factors['energy']['grid_brazil']
        return kwh * factor
    
    def _calculate_transport_emissions(self, km: float, subcategory: str) -> float:
        if subcategory in self.emission_factors['transport']:
            factor = self.emission_factors['transport'][subcategory]
        else:
            factor = self.emission_factors['transport']['gasoline_car']
        return km * factor
    
    def _calculate_materials_emissions(self, kg: float, subcategory: str) -> float:
        if subcategory in self.emission_factors['materials']:
            factor = self.emission_factors['materials'][subcategory]
        else:
            factor = 2.0
        return kg * factor
    
    def _calculate_waste_emissions(self, kg: float, subcategory: str) -> float:
        if subcategory in self.emission_factors['waste']:
            factor = self.emission_factors['waste'][subcategory]
        else:
            factor = self.emission_factors['waste']['landfill']
        return kg * factor
    
    def _calculate_water_emissions(self, m3: float, subcategory: str) -> float:
        if subcategory in self.emission_factors['water']:
            factor = self.emission_factors['water'][subcategory]
        else:
            factor = self.emission_factors['water']['treatment']
        return m3 * factor

# Inicializar calculadora
calculator = CarbonCalculator()

# Middleware para verificar login
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

# Rotas da aplicação
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/onepage')
@login_required
def onepage():
    return render_template("onepage.html")

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect('/onepage')
    return render_template("login.html")

@app.route('/relatorios')
@login_required
def relatorios():
    return render_template("relatorios.html")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# API de Autenticação
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        print("📥 Dados recebidos para registro:", data)
        
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos'}), 400
        
        required_fields = ['nome', 'email', 'senha']
        for field in required_fields:
            if field not in data or not data[field].strip():
                return jsonify({'success': False, 'message': f'Campo obrigatório: {field}'}), 400
        
        nome = data['nome'].strip()
        email = data['email'].strip()
        senha = data['senha'].strip()
        
        # Garantir que o DB está inicializado
        if not _DB_INITIALIZED:
            if not init_db():
                return jsonify({'success': False, 'message': 'Erro ao inicializar banco de dados'}), 500
        
        # Verificar se email já existe
        conn = get_db_connection()
        if not conn:
            print("❌ Erro ao conectar com o banco de dados")
            return jsonify({'success': False, 'message': 'Erro de conexão com o banco'}), 500
            
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
        if cursor.fetchone():
            conn.close()
            print("⚠️ Email já cadastrado:", email)
            return jsonify({'success': False, 'message': 'Email já cadastrado'}), 400
        
        # Hash da senha
        senha_hash = hash_password(senha)
        print("🔒 Hash da senha gerado com sucesso")
        
        # Inserir usuário
        try:
            cursor.execute(
                'INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s)',
                (nome, email, senha_hash)
            )
            conn.commit()
            user_id = cursor.lastrowid
            print("✅ Usuário cadastrado com sucesso, ID:", user_id)
        except Exception as e:
            conn.rollback()
            print(f"❌ Erro ao inserir usuário no banco: {e}")
            return jsonify({'success': False, 'message': 'Erro ao salvar usuário'}), 500
        finally:
            conn.close()
        
        # Logar usuário automaticamente
        session['user_id'] = user_id
        session['user_email'] = email
        session['user_nome'] = nome
        
        return jsonify({
            'success': True, 
            'message': 'Cadastro realizado com sucesso!',
            'user': {'id': user_id, 'nome': nome, 'email': email}
        })
        
    except Exception as e:
        print(f"❌ Erro inesperado no registro: {e}")
        return jsonify({'success': False, 'message': 'Erro interno do servidor'}), 500

@app.route('/api/login', methods=['POST'])
def login_api():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos'}), 400
        
        required_fields = ['email', 'senha']
        for field in required_fields:
            if field not in data or not data[field].strip():
                return jsonify({'success': False, 'message': f'Campo obrigatório: {field}'}), 400
        
        email = data['email'].strip()
        senha = data['senha'].strip()
        
        # Buscar usuário
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': 'Erro de conexão com o banco'}), 500
            
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
        usuario = cursor.fetchone()
        conn.close()
        
        if not usuario:
            return jsonify({'success': False, 'message': 'Email não cadastrado'}), 400
        
        # Verificar senha
        if verify_password(senha, usuario['senha']):
            session['user_id'] = usuario['id']
            session['user_email'] = usuario['email']
            session['user_nome'] = usuario['nome']
            
            return jsonify({
                'success': True, 
                'message': 'Login realizado com sucesso!',
                'user': {'id': usuario['id'], 'nome': usuario['nome'], 'email': usuario['email']}
            })
        else:
            return jsonify({'success': False, 'message': 'Senha incorreta'}), 400
        
    except Exception as e:
        print(f"Erro no login: {e}")
        return jsonify({'success': False, 'message': 'Erro interno do servidor'}), 500

# API de Emissões
@app.route('/api/calculate', methods=['POST'])
@login_required
def calculate_emissions():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Dados JSON inválidos'}), 400
        
        required_fields = ['category', 'quantity', 'unit', 'scope']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Campo obrigatório faltando: {field}'}), 400
        
        result = calculator.calculate_emissions(
            category=data['category'],
            quantity=float(data['quantity']),
            unit=data['unit'],
            subcategory=data.get('subcategory'),
            scope=data['scope']
        )
        
        # Salvar no banco
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO emissions 
                (user_id, category, subcategory, quantity, unit, scope, emissions_kg, emissions_tons, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                session['user_id'],
                result['category'],
                result['subcategory'],
                result['quantity'],
                result['unit'],
                result['scope'],
                result['emissions_kg'],
                result['emissions_tons'],
                result['timestamp']
            ))
            conn.commit()
            conn.close()
        
        return jsonify({
            'success': True,
            'data': result
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    db_status = "OK" if _DB_INITIALIZED else "NOT_INITIALIZED"
    conn = get_db_connection()
    if conn:
        conn.close()
        return jsonify({
            'status': 'OK', 
            'message': 'API e MySQL funcionando',
            'db_initialized': _DB_INITIALIZED
        })
    else:
        return jsonify({
            'status': 'ERROR', 
            'message': 'Erro na conexão MySQL',
            'db_initialized': _DB_INITIALIZED
        }), 500

@app.route('/api/reset', methods=['POST'])
@login_required
def reset_data():
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM emissions WHERE user_id = %s', (session['user_id'],))
            conn.commit()
            conn.close()
        return jsonify({'message': 'Dados resetados com sucesso'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/user')
@login_required
def get_user():
    return jsonify({
        'id': session['user_id'],
        'nome': session['user_nome'],
        'email': session['user_email']
    })

@app.route('/api/emissions/user', methods=['GET'])
@login_required
def get_user_emissions():
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Erro de conexão com o banco'}), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute('''
            SELECT id, category, subcategory, quantity, unit, scope, 
                   emissions_kg, emissions_tons, timestamp, created_at
            FROM emissions 
            WHERE user_id = %s 
            ORDER BY created_at DESC
        ''', (session['user_id'],))
        
        emissions = cursor.fetchall()
        conn.close()
        
        # Converter datetime para string se necessário
        for emission in emissions:
            if emission.get('created_at'):
                emission['created_at'] = emission['created_at'].isoformat()
        
        return jsonify({
            'success': True,
            'emissions': emissions,
            'total': len(emissions)
        })
        
    except Exception as e:
        print(f"Erro ao buscar emissões: {e}")
        return jsonify({'error': 'Erro ao buscar emissões'}), 500

if __name__ == "__main__":
    print("🔄 Inicializando banco de dados...")
    init_db()
    print("🚀 Servidor Flask iniciando...")
    if os.environ.get('VERCEL') is None:
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))