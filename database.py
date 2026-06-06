import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


class Database:
    def __init__(self, db_path='lockpicker.db'):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        """Получение соединения с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Инициализация базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Создание таблицы замков
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS castles
                           (
                               id
                               INTEGER
                               PRIMARY
                               KEY
                               AUTOINCREMENT,
                               name
                               TEXT
                               UNIQUE
                               NOT
                               NULL,
                               cells
                               INTEGER
                               NOT
                               NULL,
                               start_positions
                               TEXT
                               NOT
                               NULL,
                               dependencies
                               TEXT
                               NOT
                               NULL,
                               has_solution
                               BOOLEAN
                               DEFAULT
                               0,
                               solution_length
                               INTEGER
                               DEFAULT
                               0,
                               created_at
                               TIMESTAMP
                               DEFAULT
                               CURRENT_TIMESTAMP,
                               updated_at
                               TIMESTAMP
                               DEFAULT
                               CURRENT_TIMESTAMP
                           )
                           ''')

            # Создание таблицы глобальных настроек
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS settings
                           (
                               key
                               TEXT
                               PRIMARY
                               KEY,
                               value
                               TEXT
                               NOT
                               NULL,
                               description
                               TEXT,
                               updated_at
                               TIMESTAMP
                               DEFAULT
                               CURRENT_TIMESTAMP
                           )
                           ''')

            # Создание индексов для поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON castles(name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_solvable ON castles(has_solution)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created ON castles(created_at)')

            # Инициализация настроек по умолчанию
            self._init_default_settings(cursor)

            conn.commit()

    def _init_default_settings(self, cursor):
        """Инициализация настроек по умолчанию"""
        default_settings = {
            'min_cells': ('3', 'Минимальное количество ячеек в замке'),
            'max_cells': ('8', 'Максимальное количество ячеек в замке'),
            'target_position': ('4', 'Целевая позиция для открытия замка (центральная)'),
            'min_position': ('1', 'Минимальная позиция ячейки'),
            'max_position': ('7', 'Максимальная позиция ячейки')
        }

        for key, (value, description) in default_settings.items():
            cursor.execute('''
                           INSERT
                           OR IGNORE INTO settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
                           ''', (key, value, description, datetime.now().isoformat()))

    # Методы для работы с настройками
    def get_setting(self, key: str) -> Optional[str]:
        """Получение значения настройки"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else None

    def get_all_settings(self) -> Dict[str, Any]:
        """Получение всех настроек"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value, description FROM settings')
            rows = cursor.fetchall()
            return {row['key']: {'value': row['value'], 'description': row['description']} for row in rows}

    def update_setting(self, key: str, value: str) -> bool:
        """Обновление настройки"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                               UPDATE settings
                               SET value      = ?,
                                   updated_at = ?
                               WHERE key = ?
                               ''', (value, datetime.now().isoformat(), key))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating setting {key}: {e}")
            return False

    def update_settings_batch(self, settings: Dict[str, str]) -> bool:
        """Массовое обновление настроек"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for key, value in settings.items():
                    cursor.execute('''
                                   UPDATE settings
                                   SET value      = ?,
                                       updated_at = ?
                                   WHERE key = ?
                                   ''', (value, datetime.now().isoformat(), key))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error updating settings: {e}")
            return False

    # CRUD операции для замков
    def create_castle(self, castle_data: Dict) -> int:
        """Создание нового замка с проверкой настроек"""
        max_cells = int(self.get_setting('max_cells') or '8')
        min_cells = int(self.get_setting('min_cells') or '3')

        if castle_data['cells'] < min_cells or castle_data['cells'] > max_cells:
            raise ValueError(f"Количество ячеек должно быть от {min_cells} до {max_cells}")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO castles (name, cells, start_positions, dependencies,
                                                has_solution, solution_length, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               castle_data['name'],
                               castle_data['cells'],
                               json.dumps(castle_data['start_positions']),
                               json.dumps(castle_data['dependencies']),
                               castle_data.get('has_solution', False),
                               castle_data.get('solution_length', 0),
                               datetime.now().isoformat()
                           ))
            conn.commit()
            return cursor.lastrowid

    def get_castle(self, castle_id: int) -> Optional[Dict]:
        """Получение замка по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM castles WHERE id = ?', (castle_id,))
            row = cursor.fetchone()

            if row:
                castle = self._row_to_dict(row)
                castle['settings'] = self.get_all_settings()
                return castle
            return None

    def get_all_castles(self, search: str = None, page: int = 1, per_page: int = 12) -> Tuple[List[Dict], int]:
        """Получение всех замков с поиском и пагинацией"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Базовый запрос
            query = "SELECT * FROM castles"
            count_query = "SELECT COUNT(*) as total FROM castles"
            params = []

            # Добавляем поиск (регистронезависимый)
            if search:
                search_term = f"%{search}%"
                query += " WHERE name LIKE ? COLLATE NOCASE"
                count_query += " WHERE name LIKE ? COLLATE NOCASE"
                params.append(search_term)

            # Сортировка
            query += " ORDER BY created_at DESC"

            # Пагинация
            offset = (page - 1) * per_page
            query += " LIMIT ? OFFSET ?"
            params.extend([per_page, offset])

            # Выполняем запрос
            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Получаем общее количество
            cursor.execute(count_query, params[:1] if search else [])
            total = cursor.fetchone()['total']

            castles = [self._row_to_dict(row) for row in rows]
            settings = self.get_all_settings()
            for castle in castles:
                castle['settings'] = settings

            return castles, total

    def update_castle(self, castle_id: int, castle_data: Dict):
        """Обновление замка с проверкой настроек"""
        max_cells = int(self.get_setting('max_cells') or '8')
        min_cells = int(self.get_setting('min_cells') or '3')

        if castle_data['cells'] < min_cells or castle_data['cells'] > max_cells:
            raise ValueError(f"Количество ячеек должно быть от {min_cells} до {max_cells}")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           UPDATE castles
                           SET name            = ?,
                               cells           = ?,
                               start_positions = ?,
                               dependencies    = ?,
                               has_solution    = ?,
                               solution_length = ?,
                               updated_at      = ?
                           WHERE id = ?
                           ''', (
                               castle_data['name'],
                               castle_data['cells'],
                               json.dumps(castle_data['start_positions']),
                               json.dumps(castle_data['dependencies']),
                               castle_data.get('has_solution', False),
                               castle_data.get('solution_length', 0),
                               datetime.now().isoformat(),
                               castle_id
                           ))
            conn.commit()

    def delete_castle(self, castle_id: int):
        """Удаление замка"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM castles WHERE id = ?', (castle_id,))
            conn.commit()

    def get_stats(self) -> Dict:
        """Получение статистики"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as total FROM castles')
            total = cursor.fetchone()['total']

            cursor.execute('SELECT COUNT(*) as solvable FROM castles WHERE has_solution = 1')
            solvable = cursor.fetchone()['solvable']

            cursor.execute('SELECT AVG(solution_length) as avg_moves FROM castles WHERE has_solution = 1')
            avg_moves = cursor.fetchone()['avg_moves'] or 0

            return {
                'total': total,
                'solvable': solvable,
                'unsolvable': total - solvable,
                'avg_moves': round(avg_moves, 1)
            }

    def _row_to_dict(self, row) -> Dict:
        """Преобразование строки SQLite в словарь"""
        return {
            'id': row['id'],
            '_id': row['id'],
            'name': row['name'],
            'cells': row['cells'],
            'start_positions': json.loads(row['start_positions']),
            'dependencies': json.loads(row['dependencies']),
            'has_solution': bool(row['has_solution']),
            'solution_length': row['solution_length'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
