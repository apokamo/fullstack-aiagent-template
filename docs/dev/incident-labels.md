# インシデントラベル

Kajiが生成するincident本文はこのpathへリンクするため、互換入口として維持します。
通常Issueを含むlabel契約の正本は[Issueラベル](issue-labels.md)です。

Runtimeが所有するのは`incident`、`incident:investigating`、
`incident:cause:transient`です。Cause、severity、impact、lifecycleはartifact本文へ
記録し、incident workflowはlabelやIssue stateを変更しません。
