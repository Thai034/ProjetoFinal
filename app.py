from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
import mysql.connector
import json
from datetime import datetime
import os
from typing import Dict, List, Optional
import hashlib
import secrets

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_muito_segura_aqui_ecotrace_2025'  # Altere para uma chave segura
CORS(app)

# Configuração do Aiven MySQL (SUBSTITUA COM SUAS CREDENCIAIS)
MYSQL_CONFIG = {
    'host': 'ecotrace-mysql-thailasalvees-1966.k.aivencloud.com',  # Seu host do Aiven
    'user': 'avnadmin',              # Seu usuário do Aiven
    'password': 'AVNS_I1zukuXJ_odzJkROzFH', # Sua senha do Aiven
    'database': 'defaultdb',
    'port': 21264,                   # Porta do Aiven
    'connect_timeout': 10,
}

# Função para conectar ao MySQL (sem SSL)
def get_db_connection():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        print("✅ Conexão MySQL estabelecida com sucesso!")
        return conn
    except mysql.connector.Error as e:
        print(f"❌ Erro ao conectar com MySQL: {e}")
        return None

# Sistema de hash de senha simplificado
def hash_password(password):
    """Cria hash da senha usando SHA-256 com salt"""
    salt = "ecotrace_salt_2025_cop30"  # Você pode mudar este salt
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(password, hashed):
    """Verifica se a senha corresponde ao hash"""
    return hash_password(password) == hashed

# Fatores de emissão atualizados conforme COP30 2025
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

# Inicializar banco de dados
def init_db():
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        
        # Tabela de usuários
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                senha VARCHAR(255) NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabela de emissões
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emissions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                category TEXT NOT NULL,
                subcategory TEXT,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                scope TEXT NOT NULL,
                emissions_kg REAL NOT NULL,
                emissions_tons REAL NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Banco de dados inicializado com sucesso!")
    else:
        print("❌ Erro ao inicializar banco de dados")

# Middleware para verificar se usuário está logado
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
        
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos'}), 400
        
        required_fields = ['nome', 'email', 'senha']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'Campo obrigatório: {field}'}), 400
        
        nome = data['nome']
        email = data['email']
        senha = data['senha']
        
        # Verificar se email já existe
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': 'Erro de conexão com o banco'}), 500
            
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Email já cadastrado'}), 400
        
        # Hash da senha
        senha_hash = hash_password(senha)
        
        # Inserir usuário
        cursor.execute(
            'INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s)',
            (nome, email, senha_hash)
        )
        conn.commit()
        user_id = cursor.lastrowid
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
        print(f"Erro no registro: {e}")
        return jsonify({'success': False, 'message': 'Erro interno do servidor'}), 500

@app.route('/api/login', methods=['POST'])
def login_api():
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'Dados inválidos'}), 400
        
        required_fields = ['email', 'senha']
        for field in required_fields:
            if field not in data:
                return jsonify({'success': False, 'message': f'Campo obrigatório: {field}'}), 400
        
        email = data['email']
        senha = data['senha']
        
        # Buscar usuário
        conn = get_db_connection()
        if not conn:
            return jsonify({'success': False, 'message': 'Erro de conexão com o banco'}), 500
            
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
        usuario = cursor.fetchone()
        conn.close()
        
        if not usuario:
            return jsonify({'success': False, 'message': 'Email não cadastrado. Faça seu cadastro primeiro.'}), 400
        
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
        
        # Salvar no banco com user_id
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
    conn = get_db_connection()
    if conn:
        conn.close()
        return jsonify({'status': 'OK', 'message': 'API e MySQL funcionando'})
    else:
        return jsonify({'status': 'ERROR', 'message': 'Erro na conexão MySQL'}), 500

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

if __name__ == "__main__":
    # Inicializar banco na primeira execução
    print("🔄 Inicializando banco de dados...")
    init_db()
    print("🚀 Servidor Flask iniciando...")
    app.run(debug=True, host='0.0.0.0', port=5000)