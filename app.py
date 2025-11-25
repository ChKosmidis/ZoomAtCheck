import streamlit as st
import pandas as pd
import re
import difflib

# --- ФУНКЦИИ НОРМАЛИЗАЦИИ ---

def clean_text(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r'\W+', ' ', text).lower().strip()

def get_tokens(text):
    return set(clean_text(text).split())

def strict_clean(text):
    return re.sub(r'\W+', '', str(text)).lower()

def process_files(df_signup, df_attendance, threshold_minutes):
    # 1. Подготовка данных
    signup_col = df_signup.columns[0]
    att_name_col = df_attendance.columns[0]
    att_dur_col = df_attendance.columns[1]

    # Поиск колонок
    for col in df_attendance.columns:
        if "Имя" in col: att_name_col = col
        if "Длительность" in col: att_dur_col = col

    signup_names = df_signup[signup_col].dropna().unique()
    
    # Структура для матчинга
    signup_specs = []
    for name in signup_names:
        c_name = clean_text(name)
        tokens = get_tokens(name)
        signup_specs.append({
            'original': name, 
            'tokens': tokens,
        })

    # Создаем колонку для нормализованного имени
    df_attendance['normalized_name'] = None

    # --- ЭТАП 1: Точный поиск и токены ---
    for idx, row in df_attendance.iterrows():
        att_name_raw = row[att_name_col]
        att_tokens = get_tokens(att_name_raw)
        
        best_match = None
        best_score = 0
        
        for spec in signup_specs:
            s_tokens = spec['tokens']
            if not s_tokens or not att_tokens:
                continue
            
            common = s_tokens.intersection(att_tokens)
            score = len(common)
            is_subset = s_tokens.issubset(att_tokens) or att_tokens.issubset(s_tokens)
            
            if score >= 2:
                if score > best_score:
                    best_score = score
                    best_match = spec['original']
            elif score == 1 and is_subset and (len(s_tokens) == 1 or len(att_tokens) == 1):
                 if score > best_score:
                    best_score = score
                    best_match = spec['original']

        if best_match:
            df_attendance.at[idx, 'normalized_name'] = best_match

    # --- ЭТАП 2: Fuzzy Matching ---
    found_names = set(df_attendance['normalized_name'].dropna().unique())
    missing_signup_names = [n for n in signup_names if n not in found_names]
    
    missing_signup_map = {strict_clean(name): name for name in missing_signup_names}
    missing_keys = list(missing_signup_map.keys())

    unmatched_indices = df_attendance[df_attendance['normalized_name'].isnull()].index
    
    for idx in unmatched_indices:
        att_raw = df_attendance.at[idx, att_name_col]
        att_clean = strict_clean(att_raw)
        matches = difflib.get_close_matches(att_clean, missing_keys, n=1, cutoff=0.6)
        
        if matches:
            matched_key = matches[0]
            df_attendance.at[idx, 'normalized_name'] = missing_signup_map[matched_key]

    # --- РАСЧЕТ СТАТИСТИКИ ---
    duration_stats = df_attendance.groupby('normalized_name')[att_dur_col].sum().reset_index()
    
    present_names = set(duration_stats['normalized_name'])
    all_signup = set(signup_names)
    
    # Список 1: Не были
    not_present = sorted(list(all_signup - present_names))
    
    # Список 2: Были меньше threshold_minutes
    under_threshold = duration_stats[duration_stats[att_dur_col] < threshold_minutes].sort_values('normalized_name')
    under_threshold_list = under_threshold[['normalized_name', att_dur_col]].values.tolist()

    return not_present, under_threshold_list, df_attendance

# --- ИНТЕРФЕЙС ---

st.set_page_config(page_title="Анализ посещаемости", layout="wide")

st.title("📊 Анализ посещаемости Zoom")

# Блок настроек
with st.container():
    st.write("### 1. Настройки времени")
    col_opt, col_val = st.columns([1, 2])
    
    with col_opt:
        # Радиокнопки для выбора режима
        time_mode = st.radio(
            "Минимальное время присутствия:",
            options=["90 минут", "60 минут", "Другое"],
            horizontal=False
        )
    
    with col_val:
        # Определение итогового значения threshold
        if time_mode == "90 минут":
            threshold = 90
            st.info(f"Выбран порог: **{threshold} мин**")
        elif time_mode == "60 минут":
            threshold = 60
            st.info(f"Выбран порог: **{threshold} мин**")
        else:
            threshold = st.number_input("Введите количество минут:", min_value=1, value=45, step=5)
            st.warning(f"Будет использован ручной порог: **{threshold} мин**")

st.divider()

st.write("### 2. Загрузка файлов")
col1, col2 = st.columns(2)

with col1:
    file_signup = st.file_uploader("Загрузить 'Записались' (.csv)", type=['csv'])

with col2:
    file_attendance = st.file_uploader("Загрузить 'Посещаемость' (.csv)", type=['csv'])

if file_signup and file_attendance:
    st.divider()
    
    try:
        # Чтение с авто-определением разделителя
        try:
            df_s = pd.read_csv(file_signup)
            if df_s.shape[1] < 1: df_s = pd.read_csv(file_signup, sep=';')
        except:
             st.error("Ошибка чтения файла записи.")
        
        try:
            df_a = pd.read_csv(file_attendance, sep=';')
            if df_a.shape[1] < 2: df_a = pd.read_csv(file_attendance, sep=',')
        except:
             st.error("Ошибка чтения файла посещаемости.")

        # Обработка с учетом выбранного threshold
        not_present, under_threshold, df_debug = process_files(df_s, df_a, threshold)
        
        st.success("Готово! Результаты ниже.")
        
        res_col1, res_col2 = st.columns(2)
        
        with res_col1:
            st.subheader(f"🔴 Записались, но не пришли ({len(not_present)})")
            df_not = pd.DataFrame(not_present, columns=["Имя"])
            st.dataframe(df_not, use_container_width=True, height=400)
            
            st.download_button(
                "Скачать список отсутствующих",
                data=df_not.to_csv(index=False).encode('utf-8'),
                file_name="не_пришли.csv",
                mime="text/csv"
            )

        with res_col2:
            st.subheader(f"🟡 Были менее {threshold} минут ({len(under_threshold)})")
            df_under = pd.DataFrame(under_threshold, columns=["Имя", "Время (мин)"])
            st.dataframe(df_under, use_container_width=True, height=400)
            
            st.download_button(
                f"Скачать список (<{threshold} мин)",
                data=df_under.to_csv(index=False).encode('utf-8'),
                file_name=f"менее_{threshold}_минут.csv",
                mime="text/csv"
            )
            
        with st.expander("🔎 Детали сопоставления имен"):
             st.dataframe(df_debug[['Имя (первоначальное имя)', 'normalized_name', df_debug.columns[1]]].dropna())

    except Exception as e:
        st.error(f"Ошибка: {e}")