from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime, time as time_obj
from werkzeug.utils import secure_filename
import argparse

app = Flask(__name__)
CORS(app)

DB_PATH = './ic_manager.db'
LOG_PATH = './ic_manager.log'
EXCEL_DIR = './excel'
ALLOWED_EXTENSIONS = {'xls', 'xlsx'}

os.makedirs(EXCEL_DIR, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_table_names(area):
    if area == 'kbk_ic_cn_count':
        return ['kbk_ic_cn_count']
    elif area == 'kbk_ic_en_count':
        return ['kbk_ic_en_count']
    elif area == 'kbk_ic_nm_count':
        return ['kbk_ic_nm_count']
    else:
        return ['kbk_ic_cn_count', 'kbk_ic_en_count', 'kbk_ic_nm_count']

# 首页，直接返回管理页面
@app.route('/')
def index():
    return render_template_string("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>ICmanager 管理界面</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .section { margin-bottom: 40px; }
        label { margin-right: 10px; }
        table { border-collapse: collapse; width: 100%; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 8px; text-align: center; }
        th { background: #f0f0f0; }
        .log-box { width: 100%; height: 300px; border: 1px solid #ccc; background: #fafafa; overflow-y: scroll; padding: 10px; white-space: pre-wrap; }
    </style>
</head>
<body>
    <!-- 用餐计数管理区 -->
    <div class="section">
        <h2>用餐计数管理</h2>
        <form id="filterForm">
            <label>区域:
                <select id="areaSelect">
                    <option value="all">全部</option>
                    <option value="kbk_ic_cn_count">中餐区</option>
                    <option value="kbk_ic_en_count">西餐区</option>
                    <option value="kbk_ic_nm_count">夜市区</option>
                </select>
            </label>
            <span id="dateModeBtns">
                <button type="button" id="btnDay" onclick="setDateMode('day')">按日</button>
                <button type="button" id="btnMonth" onclick="setDateMode('month')">按月</button>
                <button type="button" id="btnYear" onclick="setDateMode('year')">按年</button>
            </span>
            <span id="dateInputs">
                <!-- 动态插入日期控件 -->
            </span>
            <label>部门: <input type="text" id="department"></label>
            <label>用户: <input type="text" id="user"></label>
            <button type="button" onclick="fetchCounts()">查询</button>
        </form>
        <table id="countTable">
            <thead>
                <tr>
                    <th>区域</th>
                    <th>计数</th>
                    <th>早</th>
                    <th>中</th>
                    <th>晚</th>
                </tr>
            </thead>
            <tbody>
                <!-- 数据填充 -->
            </tbody>
        </table>
    </div>

    <!-- 日志查看区 -->
    <div class="section">
        <h2>日志查看</h2>
        <button onclick="fetchLog()">刷新日志</button>
        <div class="log-box" id="logBox"></div>
    </div>

    <!-- Excel上传区 -->
    <div class="section">
        <h2>Excel文件上传</h2>
        <form id="uploadForm" enctype="multipart/form-data">
            <input type="file" name="excelFile" accept=".xls,.xlsx" required>
            <button type="submit">上传</button>
        </form>
        <div id="uploadResult"></div>
    </div>

    <script>
        let dateType = 'day';
        function setDateMode(mode) {
            dateType = mode;
            const dateInputs = document.getElementById('dateInputs');
            if (mode === 'day') {
                dateInputs.innerHTML = '<label>起始日期: <input type="date" id="startDate"></label>' +
                                      '<label>结束日期: <input type="date" id="endDate"></label>';
            } else if (mode === 'month') {
                dateInputs.innerHTML = '<label>起始月份: <input type="month" id="startDate"></label>' +
                                      '<label>结束月份: <input type="month" id="endDate"></label>';
            } else if (mode === 'year') {
                let yearOptions = '';
                const thisYear = new Date().getFullYear();
                for (let y = thisYear - 10; y <= thisYear + 1; y++) {
                    yearOptions += `<option value="${y}">${y}</option>`;
                }
                dateInputs.innerHTML = '<label>起始年份: <select id="startDate">' + yearOptions + '</select></label>' +
                                      '<label>结束年份: <select id="endDate">' + yearOptions + '</select></label>';
            }
        }
        // 初始化默认日期模式
        window.onload = function() {
            setDateMode('day');
            fetchCounts();
            fetchLog();
        };
        // 用餐计数查询
        function fetchCounts() {
            const area = document.getElementById('areaSelect').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const department = document.getElementById('department').value;
            const user = document.getElementById('user').value;
            fetch('/api/counts?' + new URLSearchParams({
                area, dateType, startDate, endDate, department, user
            }))
            .then(res => res.json())
            .then(data => {
                const tbody = document.getElementById('countTable').querySelector('tbody');
                tbody.innerHTML = '';
                for (const row of data.counts) {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `<td>${row.area}</td><td>${row.count}</td><td>${row.morning}</td><td>${row.noon}</td><td>${row.evening}</td>`;
                    tbody.appendChild(tr);
                }
            });
        }

        // 日志查看
        function fetchLog() {
            fetch('/api/log')
            .then(res => res.text())
            .then(text => {
                document.getElementById('logBox').textContent = text;
            });
        }

        // Excel上传
        document.getElementById('uploadForm').onsubmit = function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            fetch('/api/upload_excel', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                document.getElementById('uploadResult').textContent = data.message;
            });
        };
    </script>
</body>
</html>
    """)

@app.route('/api/counts')
def get_counts():
    area = request.args.get('area', 'all')
    date_type = request.args.get('dateType', 'day')
    start_date = request.args.get('startDate')
    end_date = request.args.get('endDate')
    department = request.args.get('department', '').strip()
    user = request.args.get('user', '').strip()

    table_names = get_table_names(area)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    result = []

    # 定义时段
    morning_start = time_obj(5, 25)
    morning_end = time_obj(7, 40)
    noon_start = time_obj(11, 25)
    noon_end = time_obj(12, 40)
    evening_start = time_obj(16, 55)
    evening_end = time_obj(19, 40)

    for table in table_names:
        sql = f"SELECT transaction_date FROM {table} WHERE 1=1"
        params = []

        if start_date:
            if date_type == 'day':
                sql += " AND date(transaction_date) >= ?"
                params.append(start_date)
            elif date_type == 'month':
                sql += " AND strftime('%Y-%m', transaction_date) >= ?"
                params.append(start_date)
            elif date_type == 'year':
                sql += " AND strftime('%Y', transaction_date) >= ?"
                params.append(start_date)
        if end_date:
            if date_type == 'day':
                sql += " AND date(transaction_date) <= ?"
                params.append(end_date)
            elif date_type == 'month':
                sql += " AND strftime('%Y-%m', transaction_date) <= ?"
                params.append(end_date)
            elif date_type == 'year':
                sql += " AND strftime('%Y', transaction_date) <= ?"
                params.append(end_date)
        if department:
            sql += " AND department = ?"
            params.append(department)
        if user:
            sql += " AND user = ?"
            params.append(user)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        count_total = len(rows)
        count_morning = 0
        count_noon = 0
        count_evening = 0

        for row in rows:
            d = row[0]
            dt = None
            try:
                dt = datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                except Exception:
                    continue
            t = dt.time()
            if morning_start <= t <= morning_end:
                count_morning += 1
            elif noon_start <= t <= noon_end:
                count_noon += 1
            elif evening_start <= t <= evening_end:
                count_evening += 1

        result.append({
            'area': table,
            'count': count_total,
            'morning': count_morning,
            'noon': count_noon,
            'evening': count_evening
        })

    conn.close()
    return jsonify({'counts': result})

@app.route('/api/log')
def get_log():
    if not os.path.exists(LOG_PATH):
        return "日志文件不存在", 404
    with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    # 直接返回日志内容，不替换换行符
    return content

@app.route('/api/upload_excel', methods=['POST'])
def upload_excel():
    if 'excelFile' not in request.files:
        return jsonify({'message': '未选择文件'}), 400
    file = request.files['excelFile']
    if file.filename == '':
        return jsonify({'message': '未选择文件'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(EXCEL_DIR, filename)
        file.save(save_path)
        return jsonify({'message': f'文件已保存到 {save_path}'})
    else:
        return jsonify({'message': '文件类型不支持'}), 400

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ICmanager 管理界面服务器')
    parser.add_argument('-p', '--port', type=int, default=5000, help='指定服务器端口（默认5000）')
    args = parser.parse_args()
    # 监听所有IP，外网可访问
    app.run(host='0.0.0.0', port=args.port, debug=True)
