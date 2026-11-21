"""Verify the installed drawing routing with its bundled Python and shipped catalog."""
import asyncio
import json
from pathlib import Path
import sys
from xml.etree import ElementTree

from deeptutor.core.context import UnifiedContext
from deeptutor.services.llm.config import LLMConfig, reset_scoped_llm_config, set_scoped_llm_config
from deeptutor.visualizers.math_tool import MathDiagramTool


async def verify():
    token = set_scoped_llm_config(LLMConfig(model="deepseek-flash", api_key="qa-no-key", provider_name="deepseek",
                                            reasoning_effort="high", max_tokens=8192))
    try:
        feedback = []
        async def sink(kind, message, _metadata=None):
            assert kind == "tool_progress"
            feedback.append(message)
        vector = UnifiedContext(user_message="能不能配个图", conversation_history=[
            {"role":"user","content":"带我学一下空间向量"}], language="zh", active_capability="chat")
        result = await MathDiagramTool().execute(_diagram_context=vector, question=vector.user_message,
                                                 purpose="student_requested", event_sink=sink)
        assert result.success and result.metadata["math_review"]["method"]=="reviewed_lesson_example", result.content
        svg = ElementTree.fromstring(result.metadata["math_figure"]["payload"]["data"])
        labels = {node.text for node in svg.iter("{http://www.w3.org/2000/svg}text")}
        assert {"O", "A", "B", "C", "a", "b", "c"} <= labels

        actual = []
        for mode, question, known in (
            ("chat", "这个二次函热图能不能做成那种动态可以被我移动的？","f(x)=s*a*(x-h)^2+k"),
            ("immersive_reading","做个简谐运动动态演示","f(x)=A*sin(2*pi*x/T)"),
        ):
            context = UnifiedContext(user_message=question, language="zh", active_capability=mode)
            result = await MathDiagramTool().execute(_diagram_context=context, question=question,
                                                     purpose="student_requested", event_sink=sink)
            assert result.success and result.metadata["math_review"]["method"]=="reviewed_interactive_lesson", result.content
            commands=result.metadata["math_figure"]["payload"]["data"]["commands"]
            assert known in commands and any("=Slider[" in command for command in commands)
            actual.append(context.user_message)
        assert sum("正在匹配" in line for line in feedback) == 3 and len(feedback) == 6
        return {"passed":True,"three_vector_labels":sorted(labels),"interactive_samples":actual,
                "feedback":feedback,"execution":sys.platform}
    finally:
        reset_scoped_llm_config(token)


Path(sys.argv[1]).write_text(json.dumps(asyncio.run(verify()),ensure_ascii=False),encoding="utf-8")
