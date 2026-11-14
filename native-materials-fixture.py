"""Seed only disposable acceptance profiles; no model or real learner data."""
def seed():
    from deeptutor.co_writer.storage import get_co_writer_storage
    from deeptutor.services.student_learning import mistakes
    text=r'''# 数学公式显示测试

| 方法 | 公式 | 条件 |
|---|---|---|
| 公式法 | $x=\dfrac{-b\pm\sqrt{b^2-4ac}}{2a}$ | $a\neq0$ |
| 配方法 | $\left(x+\frac{b}{2}\right)^2=n$ | $n\ge0$ |
| 向量 | $\overrightarrow{AC'}=x(\overrightarrow{AB}+\overrightarrow{BC})$ | 保留撇号 |
| 下标 | $x_1^2+x_2^2$ | $\Delta=b^2-4ac$ |

另一个写法：\(x=\frac{2}{3}\)。

$$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$$

代码示例：`cost = "$5"`
'''
    doc=get_co_writer_storage().create_document(title='合成数学笔记',content=text)
    old=get_co_writer_storage().create_document(title='已保存表格兼容',blocks=[{'id':'table-old','type':'table','props':{},'content':{'type':'tableContent','columnWidths':[160,360],'rows':[{'cells':[[{'type':'text','text':'已保存原文','styles':{'bold':True}}],[{'type':'text','text':r'结果 $x=\frac{2}{3}$ 与 $\Delta=b^2-4ac$','styles':{}}]]}]},'children':[]}])
    question=r'已知正方体 $ABCD-A\prime B\prime C\prime D\prime$，求 $\overrightarrow{AE}=\overrightarrow{AA\prime}+x\overrightarrow{AB}+y\overrightarrow{AD}$ 中 $x,y$。'
    record=mistakes.create_record({'manual':True,'messages':[{'id':'u','role':'user','content':question},{'id':'a','role':'user','content':r'$x=\frac{1}{2},y=\frac{1}{2}$'}]},subject='math',title='合成向量题')
    record.update(status='ready',analysis={'title':'合成向量题','subject':'math','question':{'messageId':'u','text':question},'studentWork':None,'verdict':'uncertain','explanation':r'保持依据：$\overrightarrow{AE}=\overrightarrow{AA\prime}+\frac12\overrightarrow{AB}+\frac12\overrightarrow{AD}$。','correction':r'比较系数：$x=y=\frac12$。','examPoints':[r'向量 $\overrightarrow{AB}$'],'uncertainties':[],'knowledgePoints':['向量']})
    mistakes._save(*mistakes.storage(), record)
    return {'note':doc.id,'saved_note':old.id,'mistake':record['id']}
