from collections import deque
import time
from datetime import datetime

class CastleCracker:
    def __init__(self, castle_data, timeout_seconds=30, max_states=500000):
        self.name = castle_data['name']
        self.num_cells = castle_data['cells']
        self.start = castle_data['start_positions']
        self.deps = castle_data['dependencies']

        # Получаем настройки из данных замка или используем значения по умолчанию
        settings = castle_data.get('settings', {})
        self.target_pos = int(settings.get('target_position', {}).get('value', 4))
        self.min_pos = int(settings.get('min_position', {}).get('value', 1))
        self.max_pos = int(settings.get('max_position', {}).get('value', 7))

        self.target = [self.target_pos] * self.num_cells

        # Параметры ограничений
        self.timeout_seconds = timeout_seconds
        self.max_states = max_states

        # Статистика поиска
        self.stats = {
            'states_visited': 0,
            'max_queue_size': 0,
            'time_elapsed': 0,
            'stopped_by_timeout': False,
            'stopped_by_max_states': False
        }

    def can_move(self, pos, delta):
        """Проверяет, можно ли сдвинуть позицию на delta"""
        new_pos = pos + delta
        return self.min_pos <= new_pos <= self.max_pos

    def apply_move(self, state, cell_idx, direction):
        """Применяет сдвиг для ячейки cell_idx в направлении direction (-1=влево, +1=вправо)"""
        new_state = state[:]
        deltas = {cell_idx: direction}

        deps_dict = self.deps.get(str(cell_idx + 1), {})

        for affected_cell_str, sign in deps_dict.items():
            affected_idx = int(affected_cell_str) - 1
            if sign == '+':
                affected_delta = direction
            else:
                affected_delta = -direction

            deltas[affected_idx] = deltas.get(affected_idx, 0) + affected_delta

        for idx, delta in deltas.items():
            if not self.can_move(state[idx], delta):
                return None

        for idx, delta in deltas.items():
            new_state[idx] += delta

        return new_state

    def get_possible_moves(self, state):
        """Возвращает список возможных ходов"""
        moves = []
        for cell in range(self.num_cells):
            for direction in [-1, 1]:
                if self.apply_move(state, cell, direction) is not None:
                    moves.append((cell + 1, direction))
        return moves

    def state_to_key(self, state):
        return ','.join(map(str, state))

    def get_state_hash(self, state):
        """Альтернативный хэш для больших состояний"""
        return tuple(state)

    def estimate_complexity(self):
        """Оценивает сложность поиска"""
        # Количество возможных позиций для одной ячейки
        positions_per_cell = self.max_pos - self.min_pos + 1
        # Общее количество возможных состояний
        total_states = positions_per_cell ** self.num_cells
        # Средний коэффициент ветвления
        branching_factor = self.num_cells * 2  # каждая ячейка может двигаться влево/вправо

        return {
            'total_states': total_states,
            'branching_factor': branching_factor,
            'estimated_depth': min(50, total_states // 10)  # примерная оценка
        }

    def solve(self):
        """BFS поиск решения с ограничениями"""
        start_time = time.time()
        complexity = self.estimate_complexity()

        # Предупреждение о сложности
        if complexity['total_states'] > self.max_states:
            print(f"⚠️ Внимание! Замок '{self.name}' имеет {complexity['total_states']:,} возможных состояний.")
            print(f"   Ограничение поиска: {self.max_states:,} состояний.")

        start_key = self.state_to_key(self.start)
        target_key = self.state_to_key(self.target)

        if start_key == target_key:
            self.stats['time_elapsed'] = time.time() - start_time
            return []

        queue = deque()
        queue.append((self.start, []))
        visited = {start_key}
        self.stats['states_visited'] = 1
        self.stats['max_queue_size'] = 1

        while queue:
            # Проверка времени
            if time.time() - start_time > self.timeout_seconds:
                self.stats['stopped_by_timeout'] = True
                self.stats['time_elapsed'] = time.time() - start_time
                print(f"⏰ Таймаут! Поиск прерван после {self.stats['time_elapsed']:.2f} секунд.")
                print(f"   Проверено состояний: {self.stats['states_visited']:,}")
                return None

            # Проверка количества состояний
            if self.stats['states_visited'] > self.max_states:
                self.stats['stopped_by_max_states'] = True
                self.stats['time_elapsed'] = time.time() - start_time
                print(f"📊 Достигнут лимит состояний! Проверено {self.stats['states_visited']:,} состояний.")
                return None

            state, path = queue.popleft()

            for cell, direction in self.get_possible_moves(state):
                new_state = self.apply_move(state, cell - 1, direction)
                new_key = self.state_to_key(new_state)

                if new_key not in visited:
                    self.stats['states_visited'] += 1
                    new_path = path + [(cell, direction)]

                    if new_key == target_key:
                        self.stats['time_elapsed'] = time.time() - start_time
                        return new_path

                    visited.add(new_key)
                    queue.append((new_state, new_path))

                    # Обновляем максимальный размер очереди
                    if len(queue) > self.stats['max_queue_size']:
                        self.stats['max_queue_size'] = len(queue)

            # Прогресс-бар для долгого поиска (каждые 10000 состояний)
            if self.stats['states_visited'] % 10000 == 0:
                elapsed = time.time() - start_time
                print(f"🔍 Поиск... {self.stats['states_visited']:,} состояний, "
                      f"очередь: {len(queue):,}, время: {elapsed:.1f}с")

        self.stats['time_elapsed'] = time.time() - start_time
        return None  # решение не найдено

    def get_search_stats(self):
        """Возвращает статистику поиска"""
        return self.stats

    def visualize_solution(self, solution):
        """Визуализация решения по шагам"""
        steps = []
        state = self.start[:]

        steps.append({
            'step': 0,
            'move': None,
            'state': state[:]
        })

        for step_num, (cell, direction) in enumerate(solution, 1):
            state = self.apply_move(state, cell - 1, direction)
            steps.append({
                'step': step_num,
                'move': (cell, direction),
                'state': state[:]
            })

        return steps


class IterativeDeepeningCracker(CastleCracker):
    """Альтернативный алгоритм с итеративным углублением для больших пространств"""

    def __init__(self, castle_data, timeout_seconds=30, max_depth=50):
        super().__init__(castle_data, timeout_seconds)
        self.max_depth = max_depth

    def dfs_limited(self, state, path, depth, visited, start_time):
        """DFS с ограничением глубины"""
        if time.time() - start_time > self.timeout_seconds:
            return None

        if self.state_to_key(state) == self.state_to_key(self.target):
            return path

        if depth >= self.max_depth:
            return None

        for cell, direction in self.get_possible_moves(state):
            new_state = self.apply_move(state, cell - 1, direction)
            new_key = self.state_to_key(new_state)

            if new_key not in visited:
                visited.add(new_key)
                result = self.dfs_limited(new_state, path + [(cell, direction)],
                                          depth + 1, visited, start_time)
                if result is not None:
                    return result
                visited.remove(new_key)

        return None

    def solve(self):
        """IDS - итеративное углубление"""
        start_time = time.time()

        for depth in range(1, self.max_depth + 1):
            if time.time() - start_time > self.timeout_seconds:
                self.stats['stopped_by_timeout'] = True
                return None

            visited = {self.state_to_key(self.start)}
            result = self.dfs_limited(self.start, [], 0, visited, start_time)

            if result is not None:
                self.stats['time_elapsed'] = time.time() - start_time
                return result

        return None