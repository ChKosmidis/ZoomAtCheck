import streamlit as st
import pandas as pd
import re
import difflib

def clean_text(text):
    if not isinstance(text, str):
        return ""
    # Убираем лишние символы, оставляем буквы и цифры, приводим к нижнему регистру
    return re.sub(r'\W+', ' ', text).lower().strip()

def get_tokens(text):
    return set(clean_text(text).split())

def strict_clean(text):
    # Для fuzzy matching убираем вообще все пробелы и символы
    return re.sub(r'\W+', '', str(text)).lower()

def process_files(df_signup, df_attendance):
    # 1. Подготовка данных
    # Предполагаем, что в файле "записались" имена в первой колонке
    signup_col = df_signup.columns[0]
    # В файле "посещаемость" ищем колонки по ключевым словам или берем 0 и 1
    att_name_col = df_attendance.columns[0] # Обычно "Имя (первоначальное имя)"
    att_dur_col = df_attendance.columns[1]  # Обычно "Длительность (мин)"

    # Если нашли конкретные названия колонок, используем их (для надежности)
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
            'clean': c_name, 
            'tokens': tokens,
            'strict': strict_clean(name)
        })

    # Создаем колонку для нормализованного имени
    df_attendance['normalized_name'] = None

    # --- ЭТАП 1: Точный поиск и поиск по токенам ---
    for idx, row in df_attendance.iterrows():
        att_name_raw = row[att_name_col]
        att_tokens = get_tokens(att_name_raw)
        
        best_match = None
        best_score = 0
        
        for spec in signup_specs:
            s_tokens = spec['tokens']
            if not s_tokens or not att_tokens:
                continue
            
            # Пересечение слов
            common = s_tokens.intersection(att_tokens)
            score = len(common)
            
            # Логика: если есть пересечение 2 и более слов - это почти наверняка матч
            # Или если одно слово, но оно составляет всё имя (редкие случаи)
            
            # Проверка на подмножество (если все слова из заявки есть в посещении или наоборот)
            is_subset = s_tokens.issubset(att_tokens) or att_tokens.issubset(s_tokens)
            
            if score >= 2: # Сильное совпадение
                if score > best_score:
                    best_score = score
                    best_match = spec['original']
            elif score == 1 and is_subset and (len(s_tokens) == 1 or len(att_tokens) == 1):
                 # Совпадение по 1 слову, если само имя состоит из 1 слова
                 if score > best_score:
                    best_score = score
                    best_match = spec['original']

        if best_match:
            df_attendance.at[idx, 'normalized_name'] = best_match

    # --- ЭТАП 2: Fuzzy Matching (для тех, кто не нашелся) ---
    # Собираем список тех, кого мы ЕЩЕ НЕ нашли в посещаемости (из списка записавшихся)
    found_names = set(df_attendance['normalized_name'].dropna().unique())
    missing_signup_names = [n for n in signup_names if n not in found_names]
    
    # Словарь для быстрого поиска: {очищенное_имя : оригинал}
    missing_signup_map = {strict_clean(name): name for name in missing_signup_names}
    missing_keys = list(missing_signup_map.keys())

    unmatched_indices = df_attendance[df_attendance['normalized_name'].isnull()].index
    
    for idx in unmatched_indices:
        att_raw = df_attendance.at[idx, att_name_col]
        att_clean = strict_clean(att_raw)
        
        # Ищем похожее среди потеряшек
        # cutoff=0.6 - порог похожести (как в предыдущем решении)
        matches = difflib.get_close_matches(att_clean, missing_keys, n=1, cutoff=0.6)
        
        if matches:
            matched_key = matches[0]
            original_name = missing_signup_map[matched_key]
            df_attendance.at[idx, 'normalized_name'] = original_name

    # --- РАСЧЕТ СТАТИСТИКИ ---
    
    # Группируем по нормализованному имени
    duration_stats = df_attendance.groupby('normalized_name')[att_dur_col].sum().reset_index()
    
    present_names = set(duration_stats['normalized_name'])
    all_signup = set(signup_names)
    
    # Список 1: Записались, но не были
    not_present = sorted(list(all_signup - present_names))
    
    # Список 2: Были меньше 90 минут
    under_90 = duration_stats[duration_stats[att_dur_col] < 90].sort_values('normalized_name')
    under_90_list = under_90[['normalized_name', att_dur_col]].values.tolist() # [[Name, Time], ...]

    return not_present, under_90_list, df_attendance

# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(page_title="Анализ посещаемости", layout="wide")

st.title("📊 Сверка посещаемости вебинара")
st.markdown("""
Загрузите два файла:
1. **Список записавшихся** (обычно одна колонка с именами).
2. **Отчет о посещаемости** (CSV из Zoom/Webinar, с колонками "Имя" и "Длительность").
""")

col1, col2 = st.columns(2)

with col1:
    file_signup = st.file_uploader("Загрузить файл 'Записались' (.csv)", type=['csv'])

with col2:
    file_attendance = st.file_uploader("Загрузить файл 'Посещаемость' (.csv)", type=['csv'])

if file_signup and file_attendance:
    st.divider()
    
    try:
        # Чтение файлов
        # Пробуем разные разделители, так как в первом файле запятая, во втором точка с запятой
        try:
            df_s = pd.read_csv(file_signup)
            if df_s.shape[1] < 1: # Если не считалось нормально
                 df_s = pd.read_csv(file_signup, sep=';')
        except:
             st.error("Ошибка чтения файла записи.")
        
        try:
            df_a = pd.read_csv(file_attendance, sep=';') # Чаще всего отчеты в формате ;
            if df_a.shape[1] < 2:
                df_a = pd.read_csv(file_attendance, sep=',')
        except:
             st.error("Ошибка чтения файла посещаемости.")

        st.info("Файлы загружены. Обработка...")
        
        # Запуск логики
        not_present, under_90, df_debug = process_files(df_s, df_a)
        
        # --- ВЫВОД РЕЗУЛЬТАТОВ ---
        
        st.success("Готово! Результаты ниже.")
        
        res_col1, res_col2 = st.columns(2)
        
        with res_col1:
            st.subheader(f"🔴 Записались, но не были ({len(not_present)})")
            st.write("Эти люди есть в первом файле, но не найдены во втором.")
            
            # Создаем DataFrame для красивого отображения и скачивания
            df_not_present = pd.DataFrame(not_present, columns=["Имя"])
            st.dataframe(df_not_present, height=400, use_container_width=True)
            
            # Кнопка скачивания
            csv_not = df_not_present.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Скачать список отсутствующих",
                data=csv_not,
                file_name="не_пришли.csv",
                mime="text/csv"
            )

        with res_col2:
            st.subheader(f"🟡 Были менее 90 минут ({len(under_90)})")
            st.write("Суммарное время участия меньше 1.5 часов.")
            
            df_under_90 = pd.DataFrame(under_90, columns=["Имя", "Время (мин)"])
            st.dataframe(df_under_90, height=400, use_container_width=True)
            
            csv_under = df_under_90.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Скачать список (<90 мин)",
                data=csv_under,
                file_name="менее_90_минут.csv",
                mime="text/csv"
            )

        with st.expander("🔎 Посмотреть таблицу сопоставления (для проверки)"):
            st.write("Ниже показано, как программа сопоставила имена из отчета с именами из записи.")
            st.dataframe(df_debug[['Имя (первоначальное имя)', 'normalized_name', 'Длительность (мин)']].dropna())

    except Exception as e:
        st.error(f"Произошла ошибка при обработке: {e}")
        st.write("Попробуйте проверить формат CSV файлов (кодировку или разделители).")