import streamlit as st
import pandas as pd
import re
import difflib

# --- 1. ЛОГИКА ОЧИСТКИ (С ФИЛЬТРОМ ШЕБ) ---

def clean_text(text):
    if not isinstance(text, str): return ""
    # Оставляем буквы, цифры и пробелы
    return re.sub(r'[^\w\s]', ' ', text).lower().strip()

def get_tokens(text):
    # Разбиваем на слова
    cleaned = clean_text(text)
    words = cleaned.split()
    
    # !!! СПИСОК СТОП-СЛОВ !!!
    # Эти слова будут игнорироваться при сравнении
    stop_words = {
        'шеб', 'sheb', 'школа', 'прав', 'человека', 
        'имени', 'елены', 'боннэр', 'координатор', 'волонтёров',
        'she', 'b' # на случай если разобьется
    }
    
    valid_tokens = set()
    for w in words:
        # Игнорируем стоп-слова и совсем короткий мусор (если нужно)
        if w not in stop_words and len(w) > 1:
            valid_tokens.add(w)
            
    return valid_tokens

def strict_clean(text):
    # Для нечеткого поиска удаляем мусорные слова прямо из строки
    text = text.lower()
    noise = ['шеб', 'sheb', 'школа прав человека', '|']
    for n in noise:
        text = text.replace(n, '')
    # Оставляем только буквы
    return re.sub(r'\W+', '', text)

# --- 2. ЛОГИКА СВЕРКИ ---

def process_files(df_signup, df_attendance, threshold_minutes):
    # Определяем колонки
    signup_col = df_signup.columns[0]
    att_name_col = df_attendance.columns[0]
    att_dur_col = df_attendance.columns[1]

    for col in df_attendance.columns:
        if "Имя" in col: att_name_col = col
        if "Длительность" in col: att_dur_col = col

    signup_names = df_signup[signup_col].dropna().unique()
    
    # Готовим список записавшихся
    signup_specs = []
    for name in signup_names:
        signup_specs.append({
            'original': name, 
            'tokens': get_tokens(name), # <-- Тут применяется фильтр
        })

    df_attendance['normalized_name'] = None

    # --- ЭТАП 1: Поиск по словам ---
    for idx, row in df_attendance.iterrows():
        att_name_raw = row[att_name_col]
        att_tokens = get_tokens(att_name_raw) # <-- И тут тоже
        
        best_match = None
        best_score = 0
        
        for spec in signup_specs:
            s_tokens = spec['tokens']
            if not s_tokens or not att_tokens: continue
            
            common = s_tokens.intersection(att_tokens)
            score = len(common)
            
            # Совпадение 2+ слов или 1 уникального слова
            is_subset = s_tokens.issubset(att_tokens) or att_tokens.issubset(s_tokens)
            
            if score >= 2:
                if score > best_score:
                    best_score = score
                    best_match = spec['original']
            elif score == 1 and is_subset:
                 if score > best_score:
                    best_score = score
                    best_match = spec['original']

        if best_match:
            df_attendance.at[idx, 'normalized_name'] = best_match

    # --- ЭТАП 2: Fuzzy Search (исправление опечаток) ---
    found_names = set(df_attendance['normalized_name'].dropna().unique())
    missing_signup_names = [n for n in signup_names if n not in found_names]
    
    missing_map = {strict_clean(name): name for name in missing_signup_names}
    missing_keys = list(missing_map.keys())

    unmatched_indices = df_attendance[df_attendance['normalized_name'].isnull()].index
    
    for idx in unmatched_indices:
        att_raw = df_attendance.at[idx, att_name_col]
        att_clean = strict_clean(att_raw) # <-- Убираем ШЕБ перед сравнением
        
        matches = difflib.get_close_matches(att_clean, missing_keys, n=1, cutoff=0.6)
        
        if matches:
            matched_key = matches[0]
            df_attendance.at[idx, 'normalized_name'] = missing_map[matched_key]

    # --- СТАТИСТИКА ---
    # Суммируем время
    stats = df_attendance.groupby('normalized_name')[att_dur_col].sum().reset_index()
    stats.columns = ['Имя участника', 'Время (мин)']
    stats = stats.sort_values(by='Время (мин)', ascending=False)
    
    present_names = set(stats['Имя участника'])
    all_signup = set(signup_names)
    
    # 1. Не пришли
    not_present = sorted(list(all_signup - present_names))
    
    # 2. Мало времени
    under_threshold = stats[stats['Время (мин)'] < threshold_minutes]
    
    return not_present, under_threshold, df_attendance, stats

# --- 3. ИНТЕРФЕЙС ---

st.set_page_config(page_title="Сверка Zoom", layout="wide")
st.title("📊 Сверка Zoom (с игнором 'ШЕБ')")

# Настройки
with st.container():
    col1, col2 = st.columns([1, 2])
    with col1:
        threshold = st.number_input("Минимальное время (мин):", min_value=1, value=60, step=15)
    with col2:
        st.info(f"Скрипт будет игнорировать приписки: **ШЕБ, Sheb, школа прав человека** и символы **| -**")

st.divider()

c1, c2 = st.columns(2)
with c1:
    f_signup = st.file_uploader("1. Файл 'Записались' (.csv)", type='csv')
with c2:
    f_att = st.file_uploader("2. Файл 'Посещаемость' (.csv)", type='csv')

if f_signup and f_att:
    st.divider()
    try:
        # Читаем файлы
        try:
            df_s = pd.read_csv(f_signup)
            if df_s.shape[1] < 1: df_s = pd.read_csv(f_signup, sep=';')
        except:
            st.error("Ошибка в файле записи")
            st.stop()
            
        try:
            df_a = pd.read_csv(f_att, sep=';')
            if df_a.shape[1] < 2: df_a = pd.read_csv(f_att, sep=',')
        except:
            st.error("Ошибка в файле посещаемости")
            st.stop()

        # Запуск
        not_present, under_limit, df_debug, df_full = process_files(df_s, df_a, threshold)
        
        st.success("Готово!")
        
        # Результаты
        rc1, rc2 = st.columns(2)
        
        with rc1:
            st.subheader(f"🔴 Не пришли ({len(not_present)})")
            df_not = pd.DataFrame(not_present, columns=["Имя"])
            st.dataframe(df_not, use_container_width=True, height=300)
            st.download_button("Скачать список", df_not.to_csv(index=False).encode('utf-8'), "не_пришли.csv", "text/csv")

        with rc2:
            st.subheader(f"🟡 Мало времени (<{threshold} мин) ({len(under_limit)})")
            st.dataframe(under_limit, use_container_width=True, height=300)
            st.download_button("Скачать список", under_limit.to_csv(index=False).encode('utf-8'), "мало_времени.csv", "text/csv")
            
        st.divider()
        st.subheader("📋 Полная статистика")
        st.dataframe(df_full, use_container_width=True)
        st.download_button("Скачать полную таблицу", df_full.to_csv(index=False).encode('utf-8'), "полная_статистика.csv", "text/csv")

    except Exception as e:
        st.error(f"Ошибка: {e}")