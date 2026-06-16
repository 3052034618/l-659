import json
import requests
from typing import Optional, List
from app.core.config import settings
from app.utils.logger import logger


class NotificationService:
    @staticmethod
    def send_dingtalk_alert(message: str, is_at_all: bool = False, at_mobiles: Optional[List[str]] = None) -> bool:
        if not settings.DINGTALK_WEBHOOK:
            logger.warning("钉钉Webhook未配置，跳过推送")
            return False

        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "权限合规预警",
                    "text": message
                },
                "at": {
                    "isAtAll": is_at_all,
                    "atMobiles": at_mobiles or []
                }
            }
            response = requests.post(
                settings.DINGTALK_WEBHOOK,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"钉钉预警推送成功: {message[:50]}...")
                return True
            else:
                logger.error(f"钉钉预警推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"钉钉预警推送异常: {str(e)}")
            return False

    @staticmethod
    def send_wechat_alert(message: str, mentioned_list: Optional[List[str]] = None) -> bool:
        if not settings.WECHAT_WEBHOOK:
            logger.warning("企业微信Webhook未配置，跳过推送")
            return False

        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": message
                }
            }
            if mentioned_list:
                payload["markdown"]["mentioned_list"] = mentioned_list

            response = requests.post(
                settings.WECHAT_WEBHOOK,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = response.json()
            if result.get("errcode") == 0:
                logger.info(f"企业微信预警推送成功: {message[:50]}...")
                return True
            else:
                logger.error(f"企业微信预警推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信预警推送异常: {str(e)}")
            return False

    @staticmethod
    def send_high_risk_alert(deviation_data: dict) -> bool:
        message = f"""# 🔴 高危权限偏离预警

**用户**: {deviation_data.get('username', '-')} ({deviation_data.get('full_name', '-')})
**系统**: {deviation_data.get('system_code', '-')}
**权限**: {deviation_data.get('permission_name', '-')}
**偏离类型**: {deviation_data.get('deviation_type_text', '-')}
**风险等级**: 🔴 高危
**风险分值**: {deviation_data.get('risk_score', 0)}

**详情**: {deviation_data.get('description', '')}

请安全管理员及时处理！
        """
        dingtalk_result = NotificationService.send_dingtalk_alert(message, is_at_all=True)
        wechat_result = NotificationService.send_wechat_alert(message)
        return dingtalk_result or wechat_result

    @staticmethod
    def send_ticket_escalation_alert(ticket_data: dict) -> bool:
        message = f"""# ⚠️ 审计工单升级通知

**工单号**: {ticket_data.get('ticket_no', '-')}
**标题**: {ticket_data.get('title', '-')}
**处理人**: {ticket_data.get('assignee_name', '-')}
**创建时间**: {ticket_data.get('created_at', '-')}
**超时时长**: 已超过 {settings.UPGRADE_HOURS} 小时未处理

**状态**: 已自动升级至安全总监处理

请安全总监尽快介入处理！
        """
        dingtalk_result = NotificationService.send_dingtalk_alert(message, is_at_all=True)
        wechat_result = NotificationService.send_wechat_alert(message)
        return dingtalk_result or wechat_result


notification = NotificationService()
