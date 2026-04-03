#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人工标注 Web 服务

用法（在 src/ 目录下运行）：
    conda activate slice
    python app.py
访问：http://localhost:5000
"""

import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ── 路径配置 ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # 匹配/人工标注/

DATA_FILE        = os.path.join(_ROOT, 'data.json')
ANNOTATIONS_FILE = os.path.join(_ROOT, 'annotations.json')
REPOSITORY_DIR   = os.path.join(_ROOT, 'input', 'repository')


# ── 数据加载/保存 ────────────────────────────────────────────

def load_warnings():
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f'data.json 未找到，请先运行 prepare_data.py: {DATA_FILE}')
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_annotations():
    if os.path.exists(ANNOTATIONS_FILE):
        with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_annotations(annotations):
    with open(ANNOTATIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(annotations, f, ensure_ascii=False, indent=2)


# ── 路由 ────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/warnings')
def get_warnings():
    try:
        warnings = load_warnings()
        annotations = load_annotations()
        for w in warnings:
            wid = str(w['id'])
            if wid in annotations:
                w['manual_annotation'] = annotations[wid]
            else:
                w['manual_annotation'] = None
        return jsonify({'success': True, 'data': warnings, 'total': len(warnings)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    try:
        warnings = load_warnings()
        annotations = load_annotations()
        label_counts = {'TP': 0, 'FP': 0, 'Unknown': 0}
        for ann in annotations.values():
            lbl = ann.get('label')
            if lbl in label_counts:
                label_counts[lbl] += 1
        return jsonify({
            'success': True,
            'data': {
                'total': len(warnings),
                'annotated': len(annotations),
                'unannotated': len(warnings) - len(annotations),
                'labels': label_counts,
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/annotate', methods=['POST'])
def annotate():
    try:
        data = request.get_json()
        wid = str(data.get('id'))
        label = data.get('label')
        if not wid or label not in ('TP', 'FP', 'Unknown'):
            return jsonify({'success': False, 'error': '参数错误'}), 400
        annotations = load_annotations()
        reason = data.get('reason', '')
        annotations[wid] = {'label': label, 'reason': reason, 'timestamp': datetime.now().isoformat()}
        save_annotations(annotations)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/delete_annotation/<int:wid>', methods=['DELETE'])
def delete_annotation(wid):
    try:
        annotations = load_annotations()
        key = str(wid)
        if key not in annotations:
            return jsonify({'success': False, 'error': '标注不存在'}), 404
        del annotations[key]
        save_annotations(annotations)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/file')
def get_file_content():
    """返回源文件内容（JSON）。path 参数为相对于 repository/ 的路径：{project_name_with_version}/{file_path}"""
    rel = request.args.get('path', '')
    if not rel:
        return jsonify({'success': False, 'error': '缺少 path 参数'}), 400

    # 安全检查：确保路径在 repository 目录内
    abs_path = os.path.realpath(os.path.join(REPOSITORY_DIR, rel))
    if not abs_path.startswith(os.path.realpath(REPOSITORY_DIR)):
        return jsonify({'success': False, 'error': '非法路径'}), 403

    if not os.path.isfile(abs_path):
        return jsonify({'success': False, 'error': f'文件未找到: {rel}'}), 404

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/source/<path:rel>')
def view_source_file(rel):
    """直接返回源文件原始内容，供浏览器新标签页查看。"""
    abs_path = os.path.realpath(os.path.join(REPOSITORY_DIR, rel))
    if not abs_path.startswith(os.path.realpath(REPOSITORY_DIR)):
        return '非法路径', 403
    if not os.path.isfile(abs_path):
        return f'文件未找到: {rel}', 404
    return send_file(abs_path, mimetype='text/plain; charset=utf-8')


@app.route('/api/export')
def export_data():
    try:
        warnings = load_warnings()
        annotations = load_annotations()
        result = []
        for w in warnings:
            rec = w.copy()
            wid = str(w['id'])
            if wid in annotations:
                rec['manual_annotation'] = annotations[wid]['label']
                rec['annotation_reason'] = annotations[wid].get('reason', '')
                rec['annotation_timestamp'] = annotations[wid]['timestamp']
            else:
                rec['manual_annotation'] = None
                rec['annotation_timestamp'] = None
            result.append(rec)

        fname = f'annotated_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        fpath = os.path.join('/tmp', fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return send_file(fpath, mimetype='application/json', as_attachment=True, download_name=fname)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print('=' * 60)
    print('🚀 人工标注工具启动中...')
    print(f'📂 数据文件: {DATA_FILE}')
    print(f'💾 标注文件: {ANNOTATIONS_FILE}')
    print('🌐 访问地址: http://localhost:5000')
    print('=' * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
