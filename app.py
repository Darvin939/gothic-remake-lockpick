import json
import os
import sys
import threading
import time
from datetime import datetime

import pyautogui
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response

from cracker import LockCracker
from database import Database
from localization import localization


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

app.secret_key = 'lock_cracker_secret_key_2024'
db = Database('lockpicker.db')

# Инициализация локализации
localization.init_app(app)

# Словарь для хранения активных процессов автоматизации
active_automations = {}
automation_statuses = {}


class Config:
    SOLVE_TIMEOUT = 30  # секунд
    SOLVE_MAX_STATES = 500000  # максимальное количество состояний


@app.context_processor
def utility_processor():
    return {
        'enumerate': enumerate,
        '_': localization.gettext,
        'current_lang': localization.get_language
    }


@app.route('/')
def index():
    """Главная страница"""
    stats = db.get_stats()
    settings = db.get_all_settings()
    return render_template('index.html', stats=stats, settings=settings)


@app.route('/set-language/<lang>')
def set_language(lang):
    """Переключение языка"""
    if localization.set_language(lang):
        resp = make_response(redirect(request.referrer or url_for('index')))
        resp.set_cookie('language', lang, max_age=31536000)  # 1 год
        return resp
    return redirect(request.referrer or url_for('index'))


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


@app.route('/locks')
def locks():
    """Список всех замков с поиском, фильтрацией по тегам и пагинацией"""
    search = request.args.get('search', '').strip()
    selected_tags_str = request.args.get('selected_tags', '')
    selected_tags = [t.strip() for t in selected_tags_str.split(',') if t.strip()] if selected_tags_str else []

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)

    per_page = min(per_page, 24)
    locks_list, total = db.get_all_locks(
        search=search if search else None,
        tag_filters=selected_tags if selected_tags else None,
        page=page,
        per_page=per_page
    )

    total_pages = (total + per_page - 1) // per_page
    page = min(page, total_pages) if total_pages > 0 else 1
    page_range = range(max(1, page - 2), min(total_pages, page + 2) + 1)

    settings = db.get_all_settings()
    popular_tags = db.get_all_tags(limit=50)

    return render_template('locks.html',
                           locks=locks_list,
                           search=search,
                           selected_tags=selected_tags,
                           popular_tags=popular_tags,
                           current_page=page,
                           total_pages=total_pages,
                           page_range=page_range,
                           per_page=per_page,
                           total=total,
                           settings=settings)


@app.route('/lock/new', methods=['GET', 'POST'])
def new_lock():
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
                flash('Название замка не может быть пустым', 'danger')
                return redirect(url_for('new_lock'))

            if len(name) > 100:
                flash('Название замка не может быть длиннее 100 символов', 'danger')
                return redirect(url_for('new_lock'))

            # Проверка уникальности имени
            if db.check_lock_name_exists(name):
                flash(f'Замок с именем "{name}" уже существует', 'danger')
                return redirect(url_for('new_lock'))

            # Получаем теги
            tags = request.form.getlist('tags')
            tags = [t.strip().lower() for t in tags if t.strip()]
            if len(tags) > 5:
                flash('Максимум 5 тегов на замок', 'danger')
                return redirect(url_for('new_lock'))

            lock_data = {
                'name': name,
                'cells': int(request.form['cells']),
                'start_positions': json.loads(request.form['start_positions']),
                'dependencies': json.loads(request.form['dependencies']),
                'settings': settings
            }

            # валидация
            if not (min_cells <= lock_data['cells'] <= max_cells):
                flash(f'Количество ячеек должно быть от {min_cells} до {max_cells}', 'danger')
                return redirect(url_for('new_lock'))

            if len(lock_data['start_positions']) != lock_data['cells']:
                flash(f'Должно быть {lock_data["cells"]} стартовых позиций', 'danger')
                return redirect(url_for('new_lock'))

            # Проверка стартовых позиций
            for pos in lock_data['start_positions']:
                if not (min_pos <= pos <= max_pos):
                    flash(f'Позиция {pos} вне допустимого диапазона ({min_pos}-{max_pos})', 'danger')
                    return redirect(url_for('new_lock'))

            # проверяем зависимости
            for cell, deps in lock_data['dependencies'].items():
                cell_num = int(cell)
                if cell_num < 1 or cell_num > lock_data['cells']:
                    flash(f'Ячейка {cell_num} вне диапазона', 'danger')
                    return redirect(url_for('new_lock'))

                for dep_cell, sign in deps.items():
                    dep_num = int(dep_cell)
                    if dep_num < 1 or dep_num > lock_data['cells']:
                        flash(f'Зависимая ячейка {dep_num} вне диапазона', 'danger')
                        return redirect(url_for('new_lock'))
                    if sign not in ['+', '-']:
                        flash(f'Неверный знак {sign} для зависимости', 'danger')
                        return redirect(url_for('new_lock'))

            # пробуем найти решение
            cracker = LockCracker(lock_data)
            solution = cracker.solve()
            lock_data['has_solution'] = solution is not None
            lock_data['solution_length'] = len(solution) if solution else 0

            lock_id = db.create_lock_with_tags(lock_data, tags)

            flash(f'Замок "{name}" успешно создан!', 'success')
            return redirect(url_for('lock_detail', lock_id=lock_id))

        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
            return redirect(url_for('new_lock'))

    return render_template('lock_form.html', title='Создать замок', lock=None,
                           settings=settings, min_cells=min_cells, max_cells=max_cells,
                           min_pos=min_pos, max_pos=max_pos, target_pos=target_pos)


@app.route('/lock/<int:lock_id>/edit', methods=['GET', 'POST'])
def edit_lock(lock_id):
    """Редактирование замка"""
    lock = db.get_lock(lock_id)
    if not lock:
        flash('Замок не найден', 'danger')
        return redirect(url_for('locks'))

    # Загружаем теги замка
    lock['tags'] = db.get_lock_tags(lock_id)

    settings = db.get_all_settings()
    min_cells = int(settings.get('min_cells', {}).get('value', 3))
    max_cells = int(settings.get('max_cells', {}).get('value', 8))
    min_pos = int(settings.get('min_position', {}).get('value', 1))
    max_pos = int(settings.get('max_position', {}).get('value', 7))

    if request.method == 'POST':
        try:
            name = request.form['name'].strip()
            if not name:
                flash('Название замка не может быть пустым', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            if len(name) > 100:
                flash('Название замка не может быть длиннее 100 символов', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            if db.check_lock_name_exists(name, exclude_id=lock_id):
                flash(f'Замок с именем "{name}" уже существует', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            # Получаем теги
            tags = request.form.getlist('tags')
            tags = [t.strip().lower() for t in tags if t.strip()]
            if len(tags) > 5:
                flash('Максимум 5 тегов на замок', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            lock_data = {
                'name': name,
                'cells': int(request.form['cells']),
                'start_positions': json.loads(request.form['start_positions']),
                'dependencies': json.loads(request.form['dependencies']),
                'settings': settings
            }

            # валидация
            if not (min_cells <= lock_data['cells'] <= max_cells):
                flash(f'Количество ячеек должно быть от {min_cells} до {max_cells}', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            if len(lock_data['start_positions']) != lock_data['cells']:
                flash(f'Должно быть {lock_data["cells"]} стартовых позиций', 'danger')
                return redirect(url_for('edit_lock', lock_id=lock_id))

            # Проверка стартовых позиций
            for pos in lock_data['start_positions']:
                if not (min_pos <= pos <= max_pos):
                    flash(f'Позиция {pos} вне допустимого диапазона ({min_pos}-{max_pos})', 'danger')
                    return redirect(url_for('edit_lock', lock_id=lock_id))

            # проверяем решение
            cracker = LockCracker(lock_data)
            solution = cracker.solve()
            lock_data['has_solution'] = solution is not None
            lock_data['solution_length'] = len(solution) if solution else 0

            db.update_lock_with_tags(lock_id, lock_data, tags)

            flash(f'Замок "{name}" успешно обновлён!', 'success')
            return redirect(url_for('lock_detail', lock_id=lock_id))

        except Exception as e:
            flash(f'Ошибка: {str(e)}', 'danger')
            return redirect(url_for('edit_lock', lock_id=lock_id))

    return render_template('lock_form.html', title='Редактировать замок', lock=lock,
                           settings=settings, min_cells=min_cells, max_cells=max_cells,
                           min_pos=min_pos, max_pos=max_pos,
                           target_pos=int(settings.get('target_position', {}).get('value', 4)))


@app.route('/lock/<int:lock_id>/delete', methods=['POST'])
def delete_lock(lock_id):
    """Удаление замка"""
    db.delete_lock(lock_id)
    flash('Замок успешно удалён', 'success')
    return redirect(url_for('locks'))


@app.route('/lock/<int:lock_id>')
def lock_detail(lock_id):
    """Детальная страница замка"""
    lock = db.get_lock(lock_id)
    if not lock:
        flash('Замок не найден', 'danger')
        return redirect(url_for('locks'))
    return render_template('lock_detail.html', lock=lock)


@app.route('/lock/<int:lock_id>/solve')
def solve_lock(lock_id):
    """Решение замка"""
    lock = db.get_lock(lock_id)
    if not lock:
        flash('Замок не найден', 'danger')
        return redirect(url_for('locks'))

    cracker = LockCracker(
        lock,
        timeout_seconds=Config.SOLVE_TIMEOUT,
        max_states=Config.SOLVE_MAX_STATES
    )
    solution = cracker.solve()

    if solution:
        steps = cracker.visualize_solution(solution)
        return render_template('solve_result.html', lock=lock, solution=solution, steps=steps, enumerate=enumerate)
    else:
        flash('Решение не найдено! Возможно, замок нерешаем.', 'warning')
        return redirect(url_for('lock_detail', lock_id=lock_id))


@app.route('/api/locks')
def api_locks():
    """API для получения списка замков"""
    locks = db.get_all_locks()
    return jsonify([{
        'id': lock['id'],
        'name': lock['name'],
        'cells': lock['cells'],
        'has_solution': lock['has_solution'],
        'solution_length': lock['solution_length']
    } for lock in locks])


@app.route('/lock/<int:lock_id>/export')
def export_lock(lock_id):
    """Экспорт конфигурации замка в JSON с тегами"""
    lock = db.get_lock(lock_id)
    if not lock:
        flash('Замок не найден', 'danger')
        return redirect(url_for('locks'))

    tags = db.get_lock_tags(lock_id)

    export_data = {
        'version': '1.0',
        'export_date': datetime.now().isoformat(),
        'lock': {
            'name': lock['name'],
            'cells': lock['cells'],
            'start_positions': lock['start_positions'],
            'dependencies': lock['dependencies'],
            'tags': tags
        }
    }

    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)

    # Используем только ID для имени файла (без кириллицы)
    filename = f"lock_{lock_id}.json"

    response = make_response(json_str.encode('utf-8'))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


@app.route('/locks/export-all')
def export_all_locks():
    """Экспорт всех замков в один JSON файл"""
    try:
        # Получаем список замков (игнорируем общее количество)
        locks_list, total = db.get_all_locks()

        export_data = {
            'version': '1.0',
            'export_date': datetime.now().isoformat(),
            'total_count': total,
            'locks': []
        }

        for lock in locks_list:
            tags = db.get_lock_tags(lock['id'])

            export_data['locks'].append({
                'name': lock['name'],
                'cells': lock['cells'],
                'start_positions': lock['start_positions'],
                'dependencies': lock['dependencies'],
                'tags': tags
            })

        json_str = json.dumps(export_data, ensure_ascii=False, indent=2)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"locks_export_{timestamp}.json"

        response = make_response(json_str.encode('utf-8'))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'

        flash(f'Экспортировано замков: {total}', 'success')
        return response

    except Exception as e:
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('locks'))


@app.route('/locks/import', methods=['GET', 'POST'])
def import_locks():
    """Импорт конфигураций замков из JSON"""
    if request.method == 'POST':
        try:
            # Проверяем, есть ли файл
            if 'file' not in request.files:
                flash('Файл не выбран', 'danger')
                return redirect(url_for('import_locks'))

            file = request.files['file']
            if file.filename == '':
                flash('Файл не выбран', 'danger')
                return redirect(url_for('import_locks'))

            if not file.filename.endswith('.json'):
                flash('Поддерживаются только JSON файлы', 'danger')
                return redirect(url_for('import_locks'))

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
            if 'lock' in data:
                # Формат с одним замком
                locks_to_import = [data['lock']]
            elif 'locks' in data:
                # Формат с несколькими замками
                locks_to_import = data['locks']
            else:
                # Предполагаем, что это прямой экспорт одного замка
                if 'name' in data and 'cells' in data:
                    locks_to_import = [data]
                else:
                    flash('Неверный формат файла', 'danger')
                    return redirect(url_for('import_locks'))

            for lock_data in locks_to_import:
                try:
                    # Валидация данных
                    name = lock_data.get('name', '').strip()
                    if not name:
                        errors.append(f"Пропущен: нет названия")
                        skipped_count += 1
                        continue

                    cells = int(lock_data.get('cells', 0))
                    if not (min_cells <= cells <= max_cells):
                        errors.append(f"'{name}': количество ячеек {cells} вне диапазона ({min_cells}-{max_cells})")
                        skipped_count += 1
                        continue

                    start_positions = lock_data.get('start_positions', [])
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
                    dependencies = lock_data.get('dependencies', {})
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
                    if db.check_lock_name_exists(name):
                        errors.append(f"'{name}': замок с таким именем уже существует")
                        skipped_count += 1
                        continue

                    # Создаем замок
                    new_lock = {
                        'name': name,
                        'cells': cells,
                        'start_positions': start_positions,
                        'dependencies': dependencies,
                        'settings': settings
                    }

                    # Находим решение
                    cracker = LockCracker(new_lock)
                    solution = cracker.solve()
                    new_lock['has_solution'] = solution is not None
                    new_lock['solution_length'] = len(solution) if solution else 0

                    if 'tags' in lock_data:
                        db.create_lock_with_tags(new_lock, lock_data['tags'])
                    else:
                        db.create_lock_with_tags(new_lock, [])

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

            return redirect(url_for('locks'))

        except json.JSONDecodeError as e:
            flash(f'Ошибка парсинга JSON: {str(e)}', 'danger')
            return redirect(url_for('import_locks'))
        except Exception as e:
            flash(f'Ошибка при импорте: {str(e)}', 'danger')
            return redirect(url_for('import_locks'))

    return render_template('import.html')


@app.route('/lock/<int:lock_id>/automate', methods=['POST'])
def automate_lock(lock_id):
    """Запуск автоматизации (асинхронно)"""
    lock = db.get_lock(lock_id)
    if not lock:
        return jsonify({'error': 'Замок не найден'}), 404

    # Проверяем, не запущена ли уже автоматизация
    if lock_id in active_automations and active_automations[lock_id].is_alive():
        return jsonify({'error': 'Автоматизация уже запущена'}), 400

    # Получаем настройки из запроса
    data = request.get_json()
    delay_before = data.get('delay_before', 3)
    delay_between = data.get('delay_between', 0.5)

    # Инициализируем статус
    automation_statuses[lock_id] = {
        'status': 'starting',
        'current_step': 0,
        'total_steps': 0,
        'message': 'Подготовка к запуску...'
    }

    # Запускаем автоматизацию в отдельном потоке
    def run_automation():
        try:
            # Получаем решение
            automation_statuses[lock_id]['status'] = 'loading'
            automation_statuses[lock_id]['message'] = 'Поиск решения...'

            cracker = LockCracker(lock)
            solution = cracker.solve()

            if not solution:
                automation_statuses[lock_id]['status'] = 'error'
                automation_statuses[lock_id]['message'] = 'Решение не найдено'
                return

            total_steps = len(solution)
            automation_statuses[lock_id]['total_steps'] = total_steps
            automation_statuses[lock_id]['status'] = 'waiting'
            automation_statuses[lock_id][
                'message'] = f'Найдено решение ({total_steps} шагов). Ожидание {delay_before} сек...'

            # Ждем перед началом
            time.sleep(delay_before)

            # Проверка на остановку
            if not is_automation_active(lock_id):
                automation_statuses[lock_id]['status'] = 'stopped'
                automation_statuses[lock_id]['message'] = 'Автоматизация остановлена пользователем'
                return

            automation_statuses[lock_id]['status'] = 'running'
            automation_statuses[lock_id]['message'] = 'Выполнение автоматизации...'

            # Проходим по каждому шагу решения
            current_cell = 1
            for step_num, (cell, direction) in enumerate(solution, 1):
                # Проверка на остановку
                if not is_automation_active(lock_id):
                    automation_statuses[lock_id]['status'] = 'stopped'
                    automation_statuses[lock_id][
                        'message'] = f'Автоматизация остановлена на шаге {step_num - 1}/{total_steps}'
                    return

                automation_statuses[lock_id]['current_step'] = step_num
                automation_statuses[lock_id]['message'] = f'Шаг {step_num}/{total_steps}: ячейка {cell}'

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

            automation_statuses[lock_id]['status'] = 'completed'
            automation_statuses[lock_id]['message'] = f'✅ Автоматизация завершена! Выполнено {total_steps} шагов.'

        except Exception as e:
            automation_statuses[lock_id]['status'] = 'error'
            automation_statuses[lock_id]['message'] = f'Ошибка: {str(e)}'
        finally:
            # Не удаляем статус сразу, чтобы UI мог прочитать
            pass

    # Запускаем поток
    thread = threading.Thread(target=run_automation, daemon=True)
    thread.start()
    active_automations[lock_id] = thread

    return jsonify({
        'success': True,
        'message': 'Автоматизация запущена',
        'total_steps': automation_statuses[lock_id].get('total_steps', 0)
    })


@app.route('/lock/<int:lock_id>/automate/status', methods=['GET'])
def automation_status(lock_id):
    """Получение статуса автоматизации"""
    if lock_id in automation_statuses:
        status = automation_statuses[lock_id].copy()
        status['active'] = lock_id in active_automations and active_automations[lock_id].is_alive()
        return jsonify(status)
    return jsonify({'active': False, 'status': 'idle', 'message': 'Нет активной автоматизации'})


@app.route('/lock/<int:lock_id>/automate/stop', methods=['POST'])
def stop_automation(lock_id):
    """Остановка автоматизации"""
    if lock_id in automation_statuses:
        automation_statuses[lock_id]['status'] = 'stopping'
        automation_statuses[lock_id]['message'] = 'Остановка автоматизации...'

        # Помечаем для остановки
        if lock_id in active_automations:
            # Ждем завершения потока (максимум 2 секунды)
            active_automations[lock_id].join(timeout=2)
            del active_automations[lock_id]

        automation_statuses[lock_id]['status'] = 'stopped'
        automation_statuses[lock_id]['message'] = 'Автоматизация остановлена'
        return jsonify({'success': True, 'message': 'Автоматизация остановлена'})

    return jsonify({'success': False, 'message': 'Нет активной автоматизации'})


def is_automation_active(lock_id):
    """Проверка, активна ли автоматизация"""
    if lock_id not in automation_statuses:
        return False
    status = automation_statuses[lock_id].get('status', '')
    return status in ['starting', 'loading', 'waiting', 'running'] and lock_id in active_automations


if __name__ == '__main__':
    print("🏰 Gothic1 Remake Lockpicker запущен!")
    print("📁 База данных: lockpicker.db")
    print("🌐 http://localhost:5000")
    app.run(port=5000, debug=True)
