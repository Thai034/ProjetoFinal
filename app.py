from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import json
from datetime import datetime
import os
from typing import Dict, List, Optional

app = Flask(__name__)
CORS(app)

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
        """
        Calcula emissões de carbono
        """
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
        """Converte unidades para o padrão do fator de emissão"""
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

# Banco de dados
def init_db():
    conn = sqlite3.connect('emissions.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            subcategory TEXT,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL,
            scope TEXT NOT NULL,
            emissions_kg REAL NOT NULL,
            emissions_tons REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Rotas da API
@app.route('/')
def index():
    return render_template("index.html")

@app.route('/onepage')
def onepage():
    return render_template("onepage.html")

@app.route('/login')
def login():
    return render_template("login.html")

@app.route('/relatorios')
def relatorios():
    return render_template("relatorios.html")


@app.route('/api/calculate', methods=['POST'])
def calculate_emissions():
    """Calcula emissões de carbono"""
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
        conn = sqlite3.connect('emissions.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO emissions 
            (category, subcategory, quantity, unit, scope, emissions_kg, emissions_tons, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
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
    """Health check da API"""
    return jsonify({'status': 'OK', 'message': 'API funcionando'})

@app.route('/api/reset', methods=['POST'])
def reset_data():
    """Reseta todos os dados"""
    try:
        conn = sqlite3.connect('emissions.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM emissions')
        conn.commit()
        conn.close()
        return jsonify({'message': 'Dados resetados com sucesso'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# FINALIZAR O MEU APP
if __name__ == "__main__":
    app.run(debug=True)