import streamlit as st
import pandas as pd
import re
import difflib
from pyairtable import Api

# --- НАСТРОЙКИ ---
# Чтобы не вводить их каждый раз, мы будем брать их из "Секретов" Streamlit
# Но оставим возможность ввода вручную, если секреты не настроены.

# --- ЛОГИКА НОРМАЛИЗАЦИИ ---

def clean_text(text):
    if not isinstance(text, str): return ""
    # Оставляем буквы, цифры и пробелы
    return re.sub(r'[^\w\s]', ' ', text).lower().strip()

def get_tokens(text):
    # Разбиваем на слова
    words = clean_text(text).split()
    
    # СПИСОК СТОП-СЛОВ (игнорируем их при сравнении)
    stop_words = {'шеб', 'sheb', 'ш', 'е', 'б', 'sheb', 'школа', 'прав', 'человека'}
    
    # Возвращаем набор уникальных слов, исключая стоп-слова
    # Также исключаем слишком короткие слова (меньше 2 букв), если это не инициалы
    valid_tokens = set()
    for w in words:
        if w not in stop_words and len(w) > 1:
            valid_tokens.add(w)
            
    return valid_tokens

def strict_clean(text):
    # Для нечеткого поиска убираем вообще всё лишнее
    clean = re.sub(r'\W+', '', str(text)).lower()
    # Удаляем "шеб" из строки для чистоты fuzzy match
    clean = clean.replace('шеб', '').replace('sheb', '')
    return clean

# --- ОСНОВНАЯ ЛОГИКА ---
def process_matching(signup_data, df_attendance, threshold_minutes):
    # Определение колонок
    att_name_col = df_attendance.columns[0]
    att_dur_col = df_attendance.columns[1]
    
    for col in df_attendance.columns:
        if "Имя" in col: att_name_col = col
        if "Длительность" in col: att_dur_col = col

    # Подготовка данных из Airtable
    signup_specs = []
    for person in signup_data:
        name = person['name']
        signup_specs.append({
            'original': name, 
            'tokens': get_tokens(name),
            'id': person['id']
        })

    df_attendance['matched_id'] = None
    df_attendance['normalized_name'] = None

    # 1. Точный поиск по токенам
    for idx, row in df_attendance.iterrows():
        att_name_raw = row[att_name_col]
        att_tokens = get_tokens(att_name_raw)
        
        best_match = None
        best_score = 0
        
        for spec in signup_specs:
            s_tokens = spec['tokens']
            if not s_tokens or not att_tokens: continue
            
            common = s_tokens.intersection(att_tokens)
            score = len(common)
            
            # Логика совпадения
            is_subset = s_tokens.issubset(att_tokens) or att_tokens.issubset(s_tokens)
            
            if score >= 2:
                if score > best_score:
                    best_score = score
                    best_match = spec
            elif score == 1 and is_subset:
                 # Если совпало одно слово, но это подмножество (например, редкое имя)
                 if score > best_score:
                    best_score = score
                    best_match = spec

        if best_match:
            df_attendance.at[idx, 'normalized_name'] = best_match['original']
            df_attendance.at[idx, 'matched_id'] = best_match['id']

    # 2. Нечеткий поиск (Fuzzy)
    found_ids = set(df_attendance['matched_id'].dropna().unique())
    missing_signup = [p for p in signup_data if p['id'] not in found_ids]
    
    missing_map = {strict_clean(p['name']): p for p in missing_signup}
    missing_keys = list(missing_map.keys())

    unmatched_indices = df_attendance[df_attendance['matched_id'].isnull()].index
    
    for idx in unmatched_indices:
        att_raw = df_attendance.at[idx, att_name_col]
        att_clean = strict_clean(att_raw)
        
        matches = difflib.get_close_matches(att_clean, missing_keys, n=1, cutoff=0.6)
        
        if matches:
            matched_key = matches[0]
            person = missing_map[matched_key]
            df_attendance.at[idx, 'normalized_name'] = person['name']
            df_attendance.at[idx, 'matched_id'] = person['id']

    # 3. Итоги
    stats = df_attendance.groupby('matched_id')[att_dur_col].sum().reset_index()
    passed_ids = stats[stats[att_dur_col] >= threshold_minutes]['matched_id'].tolist()
    
    final_stats = []
    for person in signup_data:
        pid = person['id']
        minutes = stats[stats['matched_id'] == pid][att_dur_col].sum() if pid in stats['matched_id'].values else 0
        status = "✅ Прошел" if pid in passed_ids else "❌ Мало/Нет"
        final_stats.append({
            "Имя": person['name'],
            "Время": minutes,
            "Статус": status
        })
        
    return passed_ids, pd.DataFrame(final_stats)

# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(page_title="Airtable Sync", layout="wide", initial_sidebar_state="expanded")
st.title("⚡ Airtable Sync + Zoom")

# Проверка секретов
if 'AIRTABLE_TOKEN' in st.secrets and 'AIRTABLE_BASE_ID' in st.secrets:
    api_token = st.secrets['AIRTABLE_TOKEN']
    base_id = st.secrets['AIRTABLE_BASE_ID']
    is_manual_auth = False
else:
    st.warning("⚠️ Токены не найдены в secrets. Введите их вручную.")
    api_token = st.sidebar.text_input("API Token", type="password")
    base_id = st.sidebar.text_input("Base ID")
    is_manual_auth = True

# Настройки таблиц (можно тоже вынести в секреты, но здесь оставим для гибкости)
with st.sidebar:
    st.header("Настройки Таблиц")
    table_meetings_name = st.text_input("Таблица Встреч", value="Встречи")
    table_participants_name = st.text_input("Таблица Участников", value="Участники")
    st.divider()
    field_signup = st.text_input("Поле 'Взялись'", value="Взялись")
    field_performer = st.text_input("Поле 'Исполнитель'", value="Исполнитель")

if not api_token or not base_id:
    st.stop()

try:
    api = Api(api_token)
    table_meetings = api.table(base_id, table_meetings_name)
    table_participants = api.table(base_id, table_participants_name)
    
    # 1. Загрузка встреч
    st.subheader("1. Выберите встречу")
    # Берем последние 30 записей
    meetings_raw = table_meetings.all(max_records=30, view="Grid view") 
    # Сортируем (попробуем найти поле даты или создания)
    meetings_raw.sort(key=lambda x: x['createdTime'], reverse=True)
    
    options = {f"{rec['fields'].get('Name', 'Без названия')} ({rec['createdTime'][:10]})": rec for rec in meetings_raw}
    selected_label = st.selectbox("Список последних встреч:", list(options.keys()))
    
    if selected_label:
        record = options[selected_label]
        signup_ids = record['fields'].get(field_signup, [])
        
        if not signup_ids:
            st.error("В поле 'Взялись' пусто.")
        else:
            st.info(f"Записано: {len(signup_ids)} чел.")
            
            # 2. Загрузка CSV
            st.subheader("2. Данные Zoom")
            col1, col2 = st.columns([2, 1])
            with col1:
                file = st.file_uploader("Файл посещаемости (.csv)", type=['csv'])
            with col2:
                threshold = st.number_input("Порог (мин):", value=60, step=15)
            
            if file:
                # Читаем CSV
                try:
                    df = pd.read_csv(file, sep=';')
                    if df.shape[1] < 2: df = pd.read_csv(file, sep=',')
                except:
                    st.error("Ошибка чтения CSV.")
                    st.stop()
                
                if st.button("🔍 Запустить сверку"):
                    with st.spinner("Загружаю участников из Airtable..."):
                        # Загружаем всех участников для маппинга
                        # (Это эффективнее, чем делать 50 запросов по одному ID)
                        all_people = table_participants.all(fields=['Name'])
                        people_map = {p['id']: p['fields'].get('Name') for p in all_people}
                        
                        signup_data = []
                        for pid in signup_ids:
                            if pid in people_map:
                                signup_data.append({'id': pid, 'name': people_map[pid]})
                    
                    # Запуск алгоритма
                    passed_ids, df_stats = process_matching(signup_data, df, threshold)
                    
                    st.write("### Результат")
                    st.dataframe(df_stats.sort_values('Время', ascending=False), use_container_width=True)
                    
                    if passed_ids:
                        if st.button(f"🚀 Записать {len(passed_ids)} чел. в Airtable"):
                            try:
                                table_meetings.update(record['id'], {field_performer: passed_ids})
                                st.success("Успешно записано!")
                                st.balloons()
                            except Exception as e:
                                st.error(f"Ошибка записи: {e}")
                    else:
                        st.warning("Никто не прошел порог времени.")

except Exception as e:
    st.error(f"Ошибка подключения к Airtable. Проверьте токен и ID базы.\nДетали: {e}")