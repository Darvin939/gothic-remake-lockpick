import json
import os
import sys

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash

from cracker import CastleCracker
from database import Database


# Функция для получения правильного пути к файлам
def resource_path(relative_path):
    """ Получить абсолютный путь к ресурсу, работает для dev и для PyInstaller """
    try:
        # PyInstaller создает временную папку и хранит путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


template_dir = resource_path('templates')
app = Flask(__name__, template_folder=template_dir)

app.secret_key = 'castle_cracker_secret_key_2024'
db = Database('lockpicker.db')


class Config:
    SOLVE_TIMEOUT = 30  # секунд
    SOLVE_MAX_STATES = 500000  # максимальное количество состояний


@app.context_processor
def utility_processor():
    return dict(enumerate=enumerate)


@app.route('/')
def index():
    """Главная страница"""
    stats = db.get_stats()
    settings = db.get_all_settings()
    return render_template('index.html', stats=stats, settings=settings)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Страница глобальных настроек"""
    if request.method == 'POST':
        try:
            new_settings = {
                'min_cells': request.form.get('min_cells', '3'),
                'max_cells': request.form.get('max_cells', '8'),
                'target_position': request.form.get('target_position', '4'),
                'min_position': request.form.get('min_position', '1'),
                'max_position': request.form.get('max_position', '7')
            }

            # Валидация
            if int(new_settings['min_cells']) < 1:
                flash('Минимальное количество ячеек не может быть меньше 1', 'danger')
                return redirect(url_for('settings'))

            if int(new_settings['max_cells']) > 20:
                flash('Максимальное количество ячеек не может быть больше 20', 'danger')
                return redirect(url_for('settings'))

            if int(new_settings['min_cells']) >= int(new_settings['max_cells']):
                flash('Минимальное количество ячеек должно быть меньше максимального', 'danger')
                return redirect(url_for('settings'))

            if int(new_settings['min_position']) >= int(new_settings['max_position']):
                flash('Минимальная позиция должна быть меньше максимальной', 'danger')
                return redirect(url_for('settings'))

            if int(new_settings['target_position']) < int(new_settings['min_position']) or \
                    int(new_settings['target_position']) > int(new_settings['max_position']):
                flash('Целевая позиция должна быть в диапазоне позиций', 'danger')
                return redirect(url_for('settings'))

            db.update_settings_batch(new_settings)
            flash('Настройки успешно сохранены!', 'success')
            return redirect(url_for('settings'))

        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
            return redirect(url_for('settings'))

    settings = db.get_all_settings()
    return render_template('settings.html', settings=settings)


@app.route('/castles')
def castles():
    """Список всех замков с поиском и пагинацией"""
    # Получаем параметры из запроса
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)

    # Ограничиваем количество на странице
    per_page = min(per_page, 24)  # максимум 24 на странице

    # Получаем данные из БД
    castles_list, total = db.get_all_castles(search=search if search else None,
                                             page=page,
                                             per_page=per_page)

    # Рассчитываем пагинацию
    total_pages = (total + per_page - 1) // per_page
    page = min(page, total_pages) if total_pages > 0 else 1

    # Диапазон страниц для отображения
    page_range = range(max(1, page - 2), min(total_pages, page + 2) + 1)

    settings = db.get_all_settings()

    return render_template('castles.html',
                           castles=castles_list,
                           search=search,
                           current_page=page,
                           total_pages=total_pages,
                           page_range=page_range,
                           per_page=per_page,
                           total=total,
                           settings=settings)


@app.route('/castle/new', methods=['GET', 'POST'])
def new_castle():
    """Создание нового замка"""
    settings = db.get_all_settings()
    min_cells = int(settings.get('min_cells', {}).get('value', 3))
    max_cells = int(settings.get('max_cells', {}).get('value', 8))
    min_pos = int(settings.get('min_position', {}).get('value', 1))
    max_pos = int(settings.get('max_position', {}).get('value', 7))
    target_pos = int(settings.get('target_position', {}).get('value', 4))

    if request.method == 'POST':
        try:
            # Валидация имени
            name = request.form['name'].strip()
            if not name:
                flash('Название замка не может быть пустым или состоять только из пробелов', 'danger')
                return redirect(url_for('new_castle'))

            if len(name) > 100:
                flash('Название замка не может быть длиннее 100 символов', 'danger')
                return redirect(url_for('new_castle'))

            castle_data = {
                'name': name,
                'cells': int(request.form['cells']),
                'start_positions': json.loads(request.form['start_positions']),
                'dependencies': json.loads(request.form['dependencies']),
                'settings': settings
            }

            # Проверка уникальности имени
            existing_castles, _ = db.get_all_castles(search=castle_data['name'])
            if existing_castles and (not castle or existing_castles[0]['id'] != castle.get('id')):
                flash(f'Замок с именем "{castle_data["name"]}" уже существует', 'danger')
                return redirect(url_for('new_castle'))

            # валидация
            if not (min_cells <= castle_data['cells'] <= max_cells):
                flash(f'Количество ячеек должно быть от {min_cells} до {max_cells}', 'danger')
                return redirect(url_for('new_castle'))

            if len(castle_data['start_positions']) != castle_data['cells']:
                flash(f'Должно быть {castle_data["cells"]} стартовых позиций', 'danger')
                return redirect(url_for('new_castle'))

            # Проверка стартовых позиций
            for pos in castle_data['start_positions']:
                if not (min_pos <= pos <= max_pos):
                    flash(f'Позиция {pos} вне допустимого диапазона ({min_pos}-{max_pos})', 'danger')
                    return redirect(url_for('new_castle'))

            # проверяем зависимости
            for cell, deps in castle_data['dependencies'].items():
                cell_num = int(cell)
                if cell_num < 1 or cell_num > castle_data['cells']:
                    flash(f'Ячейка {cell_num} вне диапазона', 'danger')
                    return redirect(url_for('new_castle'))

                for dep_cell, sign in deps.items():
                    dep_num = int(dep_cell)
                    if dep_num < 1 or dep_num > castle_data['cells']:
                        flash(f'Зависимая ячейка {dep_num} вне диапазона', 'danger')
                        return redirect(url_for('new_castle'))
                    if sign not in ['+', '-']:
                        flash(f'Неверный знак {sign} для зависимости', 'danger')
                        return redirect(url_for('new_castle'))

            # пробуем найти решение
            cracker = CastleCracker(castle_data)
            solution = cracker.solve()
            castle_data['has_solution'] = solution is not None
            castle_data['solution_length'] = len(solution) if solution else 0

            castle_id = db.create_castle(castle_data)
            flash(f'Замок "{castle_data["name"]}" успешно создан!', 'success')
            return redirect(url_for('castle_detail', castle_id=castle_id))

        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
            return redirect(url_for('new_castle'))

    return render_template('castle_form.html', title='Создать замок', castle=None,
                           settings=settings, min_cells=min_cells, max_cells=max_cells,
                           min_pos=min_pos, max_pos=max_pos, target_pos=target_pos)


@app.route('/castle/<int:castle_id>/edit', methods=['GET', 'POST'])
def edit_castle(castle_id):
    """Редактирование замка"""
    castle = db.get_castle(castle_id)
    if not castle:
        flash('Замок не найден', 'danger')
        return redirect(url_for('castles'))

    settings = db.get_all_settings()
    min_cells = int(settings.get('min_cells', {}).get('value', 3))
    max_cells = int(settings.get('max_cells', {}).get('value', 8))
    min_pos = int(settings.get('min_position', {}).get('value', 1))
    max_pos = int(settings.get('max_position', {}).get('value', 7))

    if request.method == 'POST':
        try:
            # Валидация имени
            name = request.form['name'].strip()
            if not name:
                flash('Название замка не может быть пустым или состоять только из пробелов', 'danger')
                return redirect(url_for('edit_castle', castle_id=castle_id))

            if len(name) > 100:
                flash('Название замка не может быть длиннее 100 символов', 'danger')
                return redirect(url_for('edit_castle', castle_id=castle_id))

            castle_data = {
                'name': name,
                'cells': int(request.form['cells']),
                'start_positions': json.loads(request.form['start_positions']),
                'dependencies': json.loads(request.form['dependencies']),
                'settings': settings
            }

            # Проверка уникальности имени (исключая текущий замок)
            existing_castles, _ = db.get_all_castles(search=castle_data['name'])
            if existing_castles:
                for existing in existing_castles:
                    if existing['id'] != castle_id:
                        flash(f'Замок с именем "{castle_data["name"]}" уже существует', 'danger')
                        return redirect(url_for('edit_castle', castle_id=castle_id))

            # валидация
            if not (min_cells <= castle_data['cells'] <= max_cells):
                flash(f'Количество ячеек должно быть от {min_cells} до {max_cells}', 'danger')
                return redirect(url_for('edit_castle', castle_id=castle_id))

            if len(castle_data['start_positions']) != castle_data['cells']:
                flash(f'Должно быть {castle_data["cells"]} стартовых позиций', 'danger')
                return redirect(url_for('edit_castle', castle_id=castle_id))

            # Проверка стартовых позиций
            for pos in castle_data['start_positions']:
                if not (min_pos <= pos <= max_pos):
                    flash(f'Позиция {pos} вне допустимого диапазона ({min_pos}-{max_pos})', 'danger')
                    return redirect(url_for('edit_castle', castle_id=castle_id))

            # проверяем решение
            cracker = CastleCracker(castle_data)
            solution = cracker.solve()
            castle_data['has_solution'] = solution is not None
            castle_data['solution_length'] = len(solution) if solution else 0

            db.update_castle(castle_id, castle_data)
            flash(f'Замок "{castle_data["name"]}" успешно обновлён!', 'success')
            return redirect(url_for('castle_detail', castle_id=castle_id))

        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
            return redirect(url_for('edit_castle', castle_id=castle_id))

    return render_template('castle_form.html', title='Редактировать замок', castle=castle,
                           settings=settings, min_cells=min_cells, max_cells=max_cells,
                           min_pos=min_pos, max_pos=max_pos,
                           target_pos=int(settings.get('target_position', {}).get('value', 4)))


@app.route('/castle/<int:castle_id>/delete', methods=['POST'])
def delete_castle(castle_id):
    """Удаление замка"""
    db.delete_castle(castle_id)
    flash('Замок успешно удалён', 'success')
    return redirect(url_for('castles'))


@app.route('/castle/<int:castle_id>')
def castle_detail(castle_id):
    """Детальная страница замка"""
    castle = db.get_castle(castle_id)
    if not castle:
        flash('Замок не найден', 'danger')
        return redirect(url_for('castles'))
    return render_template('castle_detail.html', castle=castle)


@app.route('/castle/<int:castle_id>/solve')
def solve_castle(castle_id):
    """Решение замка"""
    castle = db.get_castle(castle_id)
    if not castle:
        flash('Замок не найден', 'danger')
        return redirect(url_for('castles'))

    cracker = CastleCracker(
        castle,
        timeout_seconds=Config.SOLVE_TIMEOUT,
        max_states=Config.SOLVE_MAX_STATES
    )
    solution = cracker.solve()

    if solution:
        steps = cracker.visualize_solution(solution)
        return render_template('solve_result.html', castle=castle, solution=solution, steps=steps, enumerate=enumerate)
    else:
        flash('Решение не найдено! Возможно, замок нерешаем.', 'warning')
        return redirect(url_for('castle_detail', castle_id=castle_id))


@app.route('/api/castles')
def api_castles():
    """API для получения списка замков"""
    castles = db.get_all_castles()
    return jsonify([{
        'id': castle['id'],
        'name': castle['name'],
        'cells': castle['cells'],
        'has_solution': castle['has_solution'],
        'solution_length': castle['solution_length']
    } for castle in castles])


if __name__ == '__main__':
    print("🏰 Castle Cracker запущен!")
    print("📁 База данных: lockpicker.db")
    print("🌐 http://localhost:5000")
    app.run(port=5000)
