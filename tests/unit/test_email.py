import os
import sys
import pytest
import base64
from datetime import date
from email.message import EmailMessage
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import Student, Project, Assessment


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def seed_done_assessments(session):
    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/myrepo')
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/myrepo')
    session.add_all([s1, s2])
    session.commit()
    session.refresh(s1)
    session.refresh(s2)

    p1 = Project(name='项目A')
    session.add(p1)
    session.commit()
    session.refresh(p1)

    p2 = Project(name='项目B')
    session.add(p2)
    session.commit()
    session.refresh(p2)

    p3 = Project(name='项目C')
    session.add(p3)
    session.commit()
    session.refresh(p3)

    target = date(2026, 8, 21)

    a1 = Assessment(
        student_id=s1.id, project_id=p1.id, date=target,
        quality_score=80.0, match_score=75.0, total_score=78.0,
        comment='表现良好，继续加油！建议在代码规范方面多注意。',
        status='done', email_sent=False,
    )
    a2 = Assessment(
        student_id=s1.id, project_id=p2.id, date=target,
        quality_score=70.0, match_score=65.0, total_score=68.0,
        comment='还需努力，基础概念需要加强。',
        status='done', email_sent=False,
    )
    session.add_all([a1, a2])
    session.commit()

    a_s2 = Assessment(
        student_id=s2.id, project_id=p1.id, date=target,
        quality_score=90.0, match_score=85.0, total_score=88.0,
        comment='优秀！代码质量很高，建议尝试更复杂的架构设计。',
        status='done', email_sent=False,
    )
    session.add(a_s2)
    session.commit()

    a_sent = Assessment(
        student_id=s1.id, project_id=p3.id, date=target,
        quality_score=70.0, match_score=65.0, total_score=68.0,
        comment='还需努力。',
        status='done', email_sent=True,
    )
    session.add(a_sent)
    session.commit()

    return {'s1': s1, 's2': s2, 'target': target}


@pytest.fixture
def mock_settings():
    from app.config import Settings
    s = Settings()
    s.smtp_host = 'smtp.example.com'
    s.smtp_port = 587
    s.smtp_user = 'test@example.com'
    s.smtp_pass = 'testpass'
    s.smtp_from = 'noreply@example.com'
    return s


def _make_smtp_mock():
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    mock_smtp.starttls.return_value = None
    mock_smtp.login.return_value = None
    mock_smtp.sendmail.return_value = {}
    mock_smtp.quit.return_value = None
    return mock_smtp


def _get_sendmail_args(call):
    args, kwargs = call
    if kwargs:
        return kwargs.get('from_addr', args[0] if args else None), kwargs.get('to', args[1] if len(args) > 1 else []), kwargs.get('msg', args[2] if len(args) > 2 else None)
    return args[0], args[1], args[2]


def _decode_email_body(msg_str):
    """Decode a MIME message string to get the HTML body."""
    if isinstance(msg_str, str) and 'Content-Type' in msg_str:
        from email.policy import default
        msg = EmailMessage()
        msg.as_string = lambda: msg_str
        msg.as_bytes = lambda: msg_str.encode()
        # Parse manually
        parts = msg_str.split('\n\n', 1)
        if len(parts) == 2:
            body_part = parts[1].strip()
            try:
                decoded = base64.b64decode(body_part)
                return decoded.decode('utf-8')
            except Exception:
                return body_part
    return str(msg_str)


class TestSendDailyComments:

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_sends_two_emails_for_two_students(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = _make_smtp_mock()
        mock_smtp_cls.return_value = mock_smtp

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        assert mock_smtp.sendmail.call_count == 2

        calls = mock_smtp.sendmail.call_args_list
        recipients = set()
        for call in calls:
            from_addr, to_list, msg = _get_sendmail_args(call)
            recipients.update(to_list)
        assert recipients == {'zs@example.com', 'ls@example.com'}

        for call in calls:
            _, _, msg = _get_sendmail_args(call)
            body = _decode_email_body(msg)
            assert 'GitHub 日报' in body or 'GitHub' in body
            assert str(seed_done_assessments['target']) in body

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_email_body_contains_encouraging_opening_and_suggestions(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = _make_smtp_mock()
        mock_smtp_cls.return_value = mock_smtp

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        bodies = []
        for call in mock_smtp.sendmail.call_args_list:
            _, _, msg = _get_sendmail_args(call)
            bodies.append(_decode_email_body(msg))

        assert len(bodies) == 2
        full_body = '\n'.join(bodies)
        assert '鼓励' in full_body or '加油' in full_body or '表现' in full_body
        # 邮件不含分数：无总分/平均分等分数汇总
        assert '总分' not in full_body
        assert '平均分' not in full_body
        assert 'score' not in full_body.lower()
        # 但包含评语
        assert '表现良好' in full_body or '还需努力' in full_body or '优秀' in full_body

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_smtp_failure_logs_error_does_not_raise(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp
        mock_smtp.starttls.side_effect = Exception('connection refused')

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        assessments = session.exec(
            select(Assessment).where(
                Assessment.date == seed_done_assessments['target'],
                Assessment.email_sent == False,
            )
        ).all()
        for a in assessments:
            assert a.email_sent is False

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_already_sent_assessments_are_skipped(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = _make_smtp_mock()
        mock_smtp_cls.return_value = mock_smtp

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        assert mock_smtp.sendmail.call_count == 2

        sent_assessment = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_done_assessments['s1'].id,
                Assessment.date == seed_done_assessments['target'],
                Assessment.email_sent == True,
            )
        ).first()
        assert sent_assessment is not None
        assert sent_assessment.email_sent is True

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_same_student_multiple_assessments_aggregated_to_one_email(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = _make_smtp_mock()
        mock_smtp_cls.return_value = mock_smtp

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        call_recipients = {}
        for call in mock_smtp.sendmail.call_args_list:
            _, to_list, _ = _get_sendmail_args(call)
            for addr in to_list:
                call_recipients[addr] = call_recipients.get(addr, 0) + 1

        for addr, count in call_recipients.items():
            assert count == 1, f"Expected 1 email for {addr}, got {count}"

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_email_sent_marked_true_after_success(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = _make_smtp_mock()
        mock_smtp_cls.return_value = mock_smtp

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        unsent = session.exec(
            select(Assessment).where(
                Assessment.date == seed_done_assessments['target'],
                Assessment.email_sent == False,
            )
        ).all()
        assert len(unsent) == 0

    @patch('app.services.email_service.get_effective_settings')
    @patch('app.services.email_service.smtplib.SMTP')
    def test_retry_on_smtp_failure(self, mock_smtp_cls, mock_get_settings, session, seed_done_assessments, mock_settings):
        mock_get_settings.return_value = mock_settings
        mock_smtp = MagicMock()
        # Set side_effect on the class so each new instance gets the same behavior
        mock_smtp_cls.side_effect = [mock_smtp, mock_smtp]
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.starttls.side_effect = [Exception('timeout'), None]
        mock_smtp.login.return_value = None
        mock_smtp.sendmail.return_value = {}
        mock_smtp.quit.return_value = None

        from app.services.email_service import send_daily_comments
        send_daily_comments(seed_done_assessments['target'], session=session)

        assert mock_smtp.starttls.call_count >= 2


class TestEmailNeverContainsScores:
    """硬约束：邮件只发评语，任何情况下都不得出现分数。

    用户明确要求「分数永远不要发送，邮件发送是发送评语」，因此这里既做
    源码层面的静态约束，也做渲染结果的行为约束，防止后续有人往模板里加分。
    """

    _SCORE_FIELDS = (
        'total_score', 'volume_score', 'quality_score',
        'match_score', 'bonus_score', 'schedule_adjustment',
    )

    def test_build_email_source_references_no_score_field(self):
        import inspect
        from app.services import email_service
        src = inspect.getsource(email_service._build_email)
        leaked = [f for f in self._SCORE_FIELDS if f in src]
        assert leaked == [], f"_build_email 引用了分数字段: {leaked}"

    def test_rendered_body_omits_distinctive_score_values(self, session):
        """用不会与评语文字巧合的分数值，验证渲染结果不含它们。"""
        from app.services.email_service import _build_email
        st = Student(name='王五', email='ww@example.com', github_repo='ww/r')
        pj = Project(name='项目W')
        session.add_all([st, pj])
        session.commit()
        session.refresh(st)
        session.refresh(pj)
        a = Assessment(
            student_id=st.id, project_id=pj.id, date=date(2026, 8, 21),
            status='done', total_score=77.77, volume_score=66.66,
            quality_score=55.55, match_score=44.44, bonus_score=33.33,
            schedule_adjustment=-22.22, schedule_status='behind',
            comment='今天的提交结构清晰，继续保持。',
        )
        session.add(a)
        session.commit()

        subject, body = _build_email(st, [a], [None])
        rendered = subject + body
        for value in ('77.77', '66.66', '55.55', '44.44', '33.33', '22.22'):
            assert value not in rendered, f"邮件泄漏了分数 {value}"
        assert '今天的提交结构清晰，继续保持。' in body

    def test_rendered_body_omits_score_labels(self, session):
        from app.services.email_service import _build_email
        st = Student(name='赵六', email='zl@example.com', github_repo='zl/r')
        pj = Project(name='项目Z')
        session.add_all([st, pj])
        session.commit()
        session.refresh(st)
        session.refresh(pj)
        a = Assessment(
            student_id=st.id, project_id=pj.id, date=date(2026, 8, 21),
            status='done', total_score=88.0, quality_score=80.0,
            match_score=90.0, schedule_status='ontime', comment='不错',
        )
        session.add(a)
        session.commit()

        subject, body = _build_email(st, [a], [None])
        rendered = subject + body
        for label in ('总分', '得分', '评分', '分数', '代码量分',
                      '质量分', '匹配分', '进度调整', 'score', 'Score'):
            assert label not in rendered, f"邮件出现评分类字样 '{label}'"
