# 环境配置说明

## 创建 conda 环境

```bash
conda create -n matcher python=3.11 -y
conda activate matcher
pip install -r requirements.txt
```

## 依赖说明

| 包 | 用途 |
|----|------|
| `packaging` | 语义化版本号解析与排序（`packaging.version.parse`） |

## 环境验证

```bash
conda run -n matcher python -c "from packaging.version import parse; print(parse('1.2.3'))"
```

## requirements.txt

见项目根目录的 `requirements.txt`，内容：

```
packaging>=23.0
```
