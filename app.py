import json
import os
import sys
import threading
import time
from datetime import datetime

import pyautogui
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response

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

# Словарь для хранения активных процессов автоматизации
active_automations = {}
automation_statuses = {}


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
            if db.check_castle_name_exists(castle_data['name']):
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
            if db.check_castle_name_exists(castle_data['name'], exclude_id=castle_id):
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


@app.route('/castle/<int:castle_id>/export')
def export_castle(castle_id):
    """Экспорт конфигурации замка в JSON"""
    castle = db.get_castle(castle_id)
    if not castle:
        flash('Замок не найден', 'danger')
        return redirect(url_for('castles'))

    # Подготавливаем данные для экспорта
    export_data = {
        'version': '1.0',
        'export_date': datetime.now().isoformat(),
        'castle': {
            'name': castle['name'],
            'cells': castle['cells'],
            'start_positions': castle['start_positions'],
            'dependencies': castle['dependencies']
        }
    }

    # Создаем JSON строку с отступами для читаемости
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)

    # Используем только ID для имени файла (без кириллицы)
    filename = f"castle_{castle_id}.json"

    # Создаем ответ с файлом
    response = make_response(json_str.encode('utf-8'))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


@app.route('/castles/export-all')
def export_all_castles():
    """Экспорт всех замков в один JSON файл"""
    try:
        # Получаем список замков (игнорируем общее количество)
        castles_list, total = db.get_all_castles()

        export_data = {
            'version': '1.0',
            'export_date': datetime.now().isoformat(),
            'total_count': total,
            'castles': []
        }

        for castle in castles_list:
            export_data['castles'].append({
                'name': castle['name'],
                'cells': castle['cells'],
                'start_positions': castle['start_positions'],
                'dependencies': castle['dependencies']
            })

        json_str = json.dumps(export_data, ensure_ascii=False, indent=2)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"castles_export_{timestamp}.json"

        response = make_response(json_str.encode('utf-8'))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'

        flash(f'Экспортировано замков: {total}', 'success')
        return response

    except Exception as e:
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('castles'))


@app.route('/castles/import', methods=['GET', 'POST'])
def import_castles():
    """Импорт конфигураций замков из JSON"""
    if request.method == 'POST':
        try:
            # Проверяем, есть ли файл
            if 'file' not in request.files:
                flash('Файл не выбран', 'danger')
                return redirect(url_for('import_castles'))

            file = request.files['file']
            if file.filename == '':
                flash('Файл не выбран', 'danger')
                return redirect(url_for('import_castles'))

            if not file.filename.endswith('.json'):
                flash('Поддерживаются только JSON файлы', 'danger')
                return redirect(url_for('import_castles'))

            # Читаем JSON
            content = file.read().decode('utf-8')
            data = json.loads(content)

            settings = db.get_all_settings()
            min_cells = int(settings.get('min_cells', {}).get('value', 3))
            max_cells = int(settings.get('max_cells', {}).get('value', 8))
            min_pos = int(settings.get('min_position', {}).get('value', 1))
            max_pos = int(settings.get('max_position', {}).get('value', 7))

            imported_count = 0
            skipped_count = 0
            errors = []

            # Определяем формат (один замок или несколько)
            if 'castle' in data:
                # Формат с одним замком
                castles_to_import = [data['castle']]
            elif 'castles' in data:
                # Формат с несколькими замками
                castles_to_import = data['castles']
            else:
                # Предполагаем, что это прямой экспорт одного замка
                if 'name' in data and 'cells' in data:
                    castles_to_import = [data]
                else:
                    flash('Неверный формат файла', 'danger')
                    return redirect(url_for('import_castles'))

            for castle_data in castles_to_import:
                try:
                    # Валидация данных
                    name = castle_data.get('name', '').strip()
                    if not name:
                        errors.append(f"Пропущен: нет названия")
                        skipped_count += 1
                        continue

                    cells = int(castle_data.get('cells', 0))
                    if not (min_cells <= cells <= max_cells):
                        errors.append(f"'{name}': количество ячеек {cells} вне диапазона ({min_cells}-{max_cells})")
                        skipped_count += 1
                        continue

                    start_positions = castle_data.get('start_positions', [])
                    if len(start_positions) != cells:
                        errors.append(f"'{name}': неверное количество стартовых позиций")
                        skipped_count += 1
                        continue

                    # Проверка позиций
                    valid_positions = True
                    for pos in start_positions:
                        if not (min_pos <= pos <= max_pos):
                            errors.append(f"'{name}': позиция {pos} вне диапазона ({min_pos}-{max_pos})")
                            valid_positions = False
                            break

                    if not valid_positions:
                        skipped_count += 1
                        continue

                    # Проверка зависимостей
                    dependencies = castle_data.get('dependencies', {})
                    for cell, deps in dependencies.items():
                        cell_num = int(cell)
                        if cell_num < 1 or cell_num > cells:
                            errors.append(f"'{name}': ячейка {cell_num} вне диапазона")
                            valid_positions = False
                            break

                        for dep_cell, sign in deps.items():
                            dep_num = int(dep_cell)
                            if dep_num < 1 or dep_num > cells:
                                errors.append(f"'{name}': зависимая ячейка {dep_num} вне диапазона")
                                valid_positions = False
                                break
                            if sign not in ['+', '-']:
                                errors.append(f"'{name}': неверный знак '{sign}' для зависимости")
                                valid_positions = False
                                break

                    if not valid_positions:
                        skipped_count += 1
                        continue

                    # Проверяем уникальность имени
                    if db.check_castle_name_exists(name):
                        errors.append(f"'{name}': замок с таким именем уже существует")
                        skipped_count += 1
                        continue

                    # Создаем замок
                    new_castle = {
                        'name': name,
                        'cells': cells,
                        'start_positions': start_positions,
                        'dependencies': dependencies,
                        'settings': settings
                    }

                    # Находим решение
                    cracker = CastleCracker(new_castle)
                    solution = cracker.solve()
                    new_castle['has_solution'] = solution is not None
                    new_castle['solution_length'] = len(solution) if solution else 0

                    db.create_castle(new_castle)
                    imported_count += 1

                except Exception as e:
                    errors.append(f"Ошибка при импорте: {str(e)}")
                    skipped_count += 1

            # Формируем сообщение о результате
            if imported_count > 0:
                flash(f'✅ Импортировано замков: {imported_count}', 'success')
            if skipped_count > 0:
                flash(f'⚠️ Пропущено: {skipped_count}', 'warning')
                if errors and len(errors) <= 5:
                    for error in errors:
                        flash(f'• {error}', 'warning')
                elif errors:
                    flash(f'• и ещё {len(errors) - 5} ошибок...', 'warning')

            return redirect(url_for('castles'))

        except json.JSONDecodeError as e:
            flash(f'Ошибка парсинга JSON: {str(e)}', 'danger')
            return redirect(url_for('import_castles'))
        except Exception as e:
            flash(f'Ошибка при импорте: {str(e)}', 'danger')
            return redirect(url_for('import_castles'))

    return render_template('import.html')


@app.route('/castle/<int:castle_id>/automate', methods=['POST'])
def automate_castle(castle_id):
    """Запуск автоматизации (асинхронно)"""
    castle = db.get_castle(castle_id)
    if not castle:
        return jsonify({'error': 'Замок не найден'}), 404

    # Проверяем, не запущена ли уже автоматизация
    if castle_id in active_automations and active_automations[castle_id].is_alive():
        return jsonify({'error': 'Автоматизация уже запущена'}), 400

    # Получаем настройки из запроса
    data = request.get_json()
    delay_before = data.get('delay_before', 3)
    delay_between = data.get('delay_between', 0.5)

    # Инициализируем статус
    automation_statuses[castle_id] = {
        'status': 'starting',
        'current_step': 0,
        'total_steps': 0,
        'message': 'Подготовка к запуску...'
    }

    # Запускаем автоматизацию в отдельном потоке
    def run_automation():
        try:
            # Получаем решение
            automation_statuses[castle_id]['status'] = 'loading'
            automation_statuses[castle_id]['message'] = 'Поиск решения...'

            cracker = CastleCracker(castle)
            solution = cracker.solve()

            if not solution:
                automation_statuses[castle_id]['status'] = 'error'
                automation_statuses[castle_id]['message'] = 'Решение не найдено'
                return

            total_steps = len(solution)
            automation_statuses[castle_id]['total_steps'] = total_steps
            automation_statuses[castle_id]['status'] = 'waiting'
            automation_statuses[castle_id]['message'] = f'Найдено решение ({total_steps} шагов). Ожидание {delay_before} сек...'

            # Ждем перед началом
            time.sleep(delay_before)

            # Проверка на остановку
            if not is_automation_active(castle_id):
                automation_statuses[castle_id]['status'] = 'stopped'
                automation_statuses[castle_id]['message'] = 'Автоматизация остановлена пользователем'
                return

            automation_statuses[castle_id]['status'] = 'running'
            automation_statuses[castle_id]['message'] = 'Выполнение автоматизации...'

            # Проходим по каждому шагу решения
            current_cell = 1
            for step_num, (cell, direction) in enumerate(solution, 1):
                # Проверка на остановку
                if not is_automation_active(castle_id):
                    automation_statuses[castle_id]['status'] = 'stopped'
                    automation_statuses[castle_id]['message'] = f'Автоматизация остановлена на шаге {step_num-1}/{total_steps}'
                    return

                automation_statuses[castle_id]['current_step'] = step_num
                automation_statuses[castle_id]['message'] = f'Шаг {step_num}/{total_steps}: ячейка {cell}'

                # Переключаемся на нужную ячейку (W/S)
                while current_cell != cell:
                    if current_cell < cell:
                        pyautogui.press('w')
                        current_cell += 1
                    else:
                        pyautogui.press('s')
                        current_cell -= 1
                    time.sleep(0.1)

                # Двигаем позицию в нужную сторону (A/D)
                direction_key = 'a' if direction == 1 else 'd'
                pyautogui.press(direction_key)
                time.sleep(delay_between)

            automation_statuses[castle_id]['status'] = 'completed'
            automation_statuses[castle_id]['message'] = f'✅ Автоматизация завершена! Выполнено {total_steps} шагов.'

        except Exception as e:
            automation_statuses[castle_id]['status'] = 'error'
            automation_statuses[castle_id]['message'] = f'Ошибка: {str(e)}'
        finally:
            # Не удаляем статус сразу, чтобы UI мог прочитать
            pass

    # Запускаем поток
    thread = threading.Thread(target=run_automation, daemon=True)
    thread.start()
    active_automations[castle_id] = thread

    return jsonify({
        'success': True,
        'message': 'Автоматизация запущена',
        'total_steps': automation_statuses[castle_id].get('total_steps', 0)
    })

@app.route('/castle/<int:castle_id>/automate/status', methods=['GET'])
def automation_status(castle_id):
    """Получение статуса автоматизации"""
    if castle_id in automation_statuses:
        status = automation_statuses[castle_id].copy()
        status['active'] = castle_id in active_automations and active_automations[castle_id].is_alive()
        return jsonify(status)
    return jsonify({'active': False, 'status': 'idle', 'message': 'Нет активной автоматизации'})

@app.route('/castle/<int:castle_id>/automate/stop', methods=['POST'])
def stop_automation(castle_id):
    """Остановка автоматизации"""
    if castle_id in automation_statuses:
        automation_statuses[castle_id]['status'] = 'stopping'
        automation_statuses[castle_id]['message'] = 'Остановка автоматизации...'

        # Помечаем для остановки
        if castle_id in active_automations:
            # Ждем завершения потока (максимум 2 секунды)
            active_automations[castle_id].join(timeout=2)
            del active_automations[castle_id]

        automation_statuses[castle_id]['status'] = 'stopped'
        automation_statuses[castle_id]['message'] = 'Автоматизация остановлена'
        return jsonify({'success': True, 'message': 'Автоматизация остановлена'})

    return jsonify({'success': False, 'message': 'Нет активной автоматизации'})

def is_automation_active(castle_id):
    """Проверка, активна ли автоматизация"""
    if castle_id not in automation_statuses:
        return False
    status = automation_statuses[castle_id].get('status', '')
    return status in ['starting', 'loading', 'waiting', 'running'] and castle_id in active_automations


if __name__ == '__main__':
    print("🏰 Gothic1 Remake Lockpicker запущен!")
    print("📁 База данных: lockpicker.db")
    print("🌐 http://localhost:5000")
    app.run(port=5000)
