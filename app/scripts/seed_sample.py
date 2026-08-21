"""Generate sample xlsx fixture files for the GitHub daily tracker.

Produces:
  tests/fixtures/sample_students.xlsx   — students (mixed CN/EN columns, one invalid row)
  tests/fixtures/sample_projects.xlsx   — 3 projects
  tests/fixtures/sample_plans.xlsx      — all-student + per-student plans
"""

from openpyxl import Workbook


def _save(path: str, headers: list[str], rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


def _students() -> None:
    _save(
        "tests/fixtures/sample_students.xlsx",
        ["学生姓名", "email", "github仓库", "学号"],
        [
            ["张三", "zhangsan@example.com", "https://github.com/zhangsan/todo-app", "2024001"],
            ["李四", "lisi@example.com", "lisi/data-project", "2024002"],
            ["王五", "wangwu@example.com", "wangwu/webapp", "2024003"],
            # 无效行：缺少邮箱
            ["赵六", "", "zhaoliu/empty-email", "2024004"],
        ],
    )


def _projects() -> None:
    _save(
        "tests/fixtures/sample_projects.xlsx",
        ["项目名称", "描述", "开始日期", "结束日期"],
        [
            ["Python入门", "学习Python基础语法与数据结构", "2026-08-01", "2026-09-30"],
            ["数据分析", "pandas/numpy 数据分析入门", "2026-08-15", None],
            ["Web开发", "Flask 轻量级 Web 应用开发", None, None],
        ],
    )


def _plans() -> None:
    _save(
        "tests/fixtures/sample_plans.xlsx",
        ["日期", "project_name", "工作计划", "学生姓名"],
        [
            # 全员计划
            ["2026-08-21", "Python入门", "完成变量与数据类型练习", None],
            ["2026-08-22", "数据分析", "阅读第三章：数据清洗", None],
            # 专属学生计划
            ["2026-08-21", "Python入门", "张三专属：额外完成函数章节练习", "张三"],
            ["2026-08-22", "Web开发", "李四专属：搭建 Flask 骨架项目", "李四"],
        ],
    )


if __name__ == "__main__":
    _students()
    _projects()
    _plans()
    print("Generated: tests/fixtures/sample_students.xlsx")
    print("Generated: tests/fixtures/sample_projects.xlsx")
    print("Generated: tests/fixtures/sample_plans.xlsx")
