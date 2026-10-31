from leornian.modules.item_bank.contracts import Exercise, PublishedItem

VERSION = "python-even-sum.v1"


def published_item(version: str) -> PublishedItem:
    if version != VERSION:
        raise ValueError("Unsupported curated exercise version")
    return PublishedItem(
        exercise=Exercise(
            version=VERSION,
            title="筛选并求和：把偶数加起来",
            prompt=(
                "编写 Python 程序，从标准输入读取一行 JSON 整数数组，只向标准输出打印其中偶数的和。"
                "空数组的和为 0；负偶数也应计入。例：[1, 2, 3, 4] 输出 6。"
                "练习不需要网络或文件；不要打印提示语。仅三组基础用例，不代表独立掌握度认证。"
            ),
            starter_code=(
                "import json\nimport sys\n\nnumbers = json.loads(sys.stdin.readline())\n"
                "# Add the even numbers, then print the result.\nprint(0)\n"
            ),
            provenance="Leornian 人工编写入门样例 v1；非动态供题、非六角色审核题包。",
        ),
        execution_inputs=[[1, 2, 3, 4], [], [-6, -3, 0, 8, 11, 12]],
    )
