from datetime import datetime
from typing import Literal
from uuid import UUID

from leornian.shared_kernel.contracts import Contract


class TrackInput(Contract):
    goal_id: UUID
    course_version: Literal["python-even-sum.v1"] = "python-even-sum.v1"


class ConfirmPlan(Contract):
    expected_revision: int


class Track(Contract):
    id: UUID
    goal_id: UUID
    course_version: Literal["python-even-sum.v1"]
    revision: int
    status: Literal["draft", "confirmed", "completed"]
    created_at: datetime
    confirmed_at: datetime | None
    completed_at: datetime | None


class Lesson(Contract):
    title: str = "用循环筛选偶数并累加"
    body: str = (
        "这一节练习把一个小问题拆成读取、筛选、累加、输出四步。\n\n"
        "1. 用 json.loads 读取标准输入中的整数数组。数组只是数据，不要把输入当代码执行。\n"
        "2. 用 for 遍历数组。每次循环处理一个整数。\n"
        "3. 用 number % 2 == 0 判断偶数；Python 的负偶数同样能整除 2。\n"
        "4. 累加器从 0 开始，只累加满足条件的数字，最后输出一次。\n\n"
        "先想一想：如果数组为空，循环会执行几次？最终累加器应该是什么？\n"
        "本课是固定 Python 入门样例，不是根据任意目标生成的完整计划。"
    )
