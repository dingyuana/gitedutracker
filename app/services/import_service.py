import pandas as pd
from sqlmodel import Session, select
from datetime import date
from app.models import Student, Project, DailyPlan


STUDENT_COLUMN_ALIASES = {
    '学生姓名': 'name', 'student_name': 'name',
    'github仓库': 'github_repo', 'github_repo': 'github_repo', '仓库地址': 'github_repo',
    '邮箱': 'email', 'email': 'email',
    '学号': 'student_no', 'student_no': 'student_no',
}

PROJECT_COLUMN_ALIASES = {
    '项目名称': 'name', 'project_name': 'name',
    '描述': 'description', 'description': 'description',
    '开始日期': 'start_date', 'start_date': 'start_date',
    '结束日期': 'end_date', 'end_date': 'end_date',
}

PLAN_COLUMN_ALIASES = {
    '日期': 'date', 'date': 'date',
    '项目名称': 'project_name', 'project_name': 'project_name',
    '工作计划': 'content', 'plan_content': 'content',
    '学生姓名': 'student_name', 'student_name': 'student_name',
}


def _normalize_columns(df: pd.DataFrame, aliases: dict) -> pd.DataFrame:
    col_map = {}
    for col in df.columns:
        if col in aliases:
            col_map[col] = aliases[col]
    return df.rename(columns=col_map)


def _ensure_columns(df: pd.DataFrame, required: list, entity: str, col_names: dict = None):
    _std_to_cn = {'name': '项目名称', 'email': '邮箱', 'github_repo': 'github仓库',
                  'student_no': '学号', 'project_name': '项目名称', 'date': '日期',
                  'content': '工作计划', 'description': '描述', 'start_date': '开始日期',
                  'end_date': '结束日期', 'student_name': '学生姓名',
                  **(col_names or {})}
    missing = [c for c in required if c not in df.columns]
    if missing:
        display = [_std_to_cn.get(c, c) for c in missing]
        raise ValueError(f"{entity} 缺少必填列: {', '.join(display)}")


def _parse_date(val):
    if pd.isna(val):
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, pd.Timestamp):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def import_students(filepath: str, session: Session = None) -> int:
    df = pd.read_excel(filepath, engine='openpyxl')
    df = _normalize_columns(df, STUDENT_COLUMN_ALIASES)
    _ensure_columns(df, ['name', 'email', 'github_repo'], '学生表', col_names={'name': '学生姓名'})

    count = 0
    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel 行号（含表头）
        email = row.get('email')
        if pd.isna(email) or str(email).strip() == '':
            raise ValueError(f"学生表第 {row_num} 行缺少必填列「邮箱」")
        repo = row.get('github_repo')
        if pd.isna(repo) or str(repo).strip() == '':
            raise ValueError(f"学生表第 {row_num} 行缺少必填列「github仓库」")
        student_data = {
            'name': str(row['name']).strip(),
            'email': str(email).strip(),
            'github_repo': str(repo).strip(),
        }
        if 'student_no' in df.columns and not pd.isna(row.get('student_no')):
            student_data['student_no'] = str(row['student_no']).strip()
        existing = session.exec(
            select(Student).where(Student.email == student_data['email'])
        ).first()
        if existing is not None:
            existing.name = student_data['name']
            existing.github_repo = student_data['github_repo']
            if 'student_no' in student_data:
                existing.student_no = student_data['student_no']
            session.add(existing)
        else:
            s = Student.model_validate(student_data)
            session.add(s)
        count += 1
    session.commit()
    return count


def import_projects(filepath: str, session: Session = None) -> int:
    df = pd.read_excel(filepath, engine='openpyxl')
    df = _normalize_columns(df, PROJECT_COLUMN_ALIASES)
    _ensure_columns(df, ['name'], '项目表')

    count = 0
    for _, row in df.iterrows():
        name = row.get('name')
        if pd.isna(name) or str(name).strip() == '':
            raise ValueError("项目表存在空项目名称行")
        project_data = {
            'name': str(name).strip(),
        }
        if 'description' in df.columns and not pd.isna(row.get('description')):
            project_data['description'] = str(row['description']).strip()
        if 'start_date' in df.columns and not pd.isna(row.get('start_date')):
            project_data['start_date'] = _parse_date(row['start_date'])
        if 'end_date' in df.columns and not pd.isna(row.get('end_date')):
            project_data['end_date'] = _parse_date(row['end_date'])
        p = Project.model_validate(project_data)
        session.add(p)
        count += 1
    session.commit()
    return count


def import_daily_plans(filepath: str, session: Session = None) -> int:
    df = pd.read_excel(filepath, engine='openpyxl')
    df = _normalize_columns(df, PLAN_COLUMN_ALIASES)
    _ensure_columns(df, ['date', 'project_name'], '计划表')

    # 预加载项目名→id 映射
    projects = {p.name: p.id for p in session.exec(select(Project)).all()}

    count = 0
    for _, row in df.iterrows():
        plan_date = _parse_date(row.get('date'))
        if plan_date is None:
            raise ValueError("计划表存在无效的日期行")
        project_name = str(row['project_name']).strip()
        if project_name not in projects:
            available = ', '.join(projects.keys()) if projects else '(无项目)'
            raise ValueError(f"项目「{project_name}」不存在，可用项目: {available}")
        content = row.get('content')
        if pd.isna(content) or str(content).strip() == '':
            raise ValueError("计划表存在空工作计划行")
        plan_data = {
            'date': plan_date,
            'project_id': projects[project_name],
            'content': str(content).strip(),
        }
        if 'student_name' in df.columns and not pd.isna(row.get('student_name')):
            student_name = str(row['student_name']).strip()
            student = session.exec(select(Student).where(Student.name == student_name)).first()
            if student:
                plan_data['student_id'] = student.id
        dp = DailyPlan.model_validate(plan_data)
        session.add(dp)
        count += 1
    session.commit()
    return count
