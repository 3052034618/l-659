from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Tuple
import requests
import json
from app.core.config import settings
from app.utils import logger


class BusinessSystemAdapter(ABC):
    @abstractmethod
    def fetch_permissions(self, user_identifier: str, system_code: str) -> Tuple[bool, Optional[Dict[str, bool]], str]:
        pass

    @abstractmethod
    def adjust_permission(self, user_identifier: str, system_code: str,
                          permission_code: str, grant: bool) -> Tuple[bool, str]:
        pass


class RealBusinessSystemAdapter(BusinessSystemAdapter):
    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def _get_system_info(self, system_code: str) -> Optional[dict]:
        for sys in settings.BUSINESS_SYSTEMS:
            if sys["code"] == system_code:
                return sys
        return None

    def fetch_permissions(self, user_identifier: str, system_code: str) -> Tuple[bool, Optional[Dict[str, bool]], str]:
        sys_info = self._get_system_info(system_code)
        if not sys_info:
            return False, None, f"系统[{system_code}]未配置"

        api_url = sys_info.get("api_url", "")
        if not api_url:
            return False, None, f"系统[{system_code}]API地址未配置"

        try:
            url = f"{api_url.rstrip('/')}/permissions"
            payload = {
                "user_identifier": user_identifier,
                "system_code": system_code,
            }

            logger.info(f"调用真实系统接口获取权限: {system_code} -> {user_identifier}, URL={url}")

            response = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )

            if response.status_code != 200:
                return False, None, (
                    f"接口调用失败: HTTP {response.status_code}, "
                    f"系统[{sys_info['name']}]响应异常: {response.text[:200]}"
                )

            result = response.json()
            if not result.get("success", False):
                return False, None, (
                    f"业务系统返回失败: 系统[{sys_info['name']}], "
                    f"错误信息: {result.get('message', '未知错误')}"
                )

            permissions = result.get("data", {}).get("permissions", {})
            if not isinstance(permissions, dict):
                return False, None, f"接口返回数据格式错误，permissions应为字典类型"

            return True, permissions, f"成功从[{sys_info['name']}]获取{len(permissions)}项权限"

        except requests.Timeout:
            return False, None, (
                f"调用[{sys_info['name']}]接口超时(>{self.timeout}秒)，"
                f"请检查网络连接或系统可用性"
            )
        except requests.ConnectionError:
            return False, None, (
                f"无法连接到[{sys_info['name']}]系统({api_url})，"
                f"网络不通或服务未启动"
            )
        except requests.RequestException as e:
            return False, None, (
                f"调用[{sys_info['name']}]接口异常: {type(e).__name__}: {str(e)[:100]}"
            )
        except json.JSONDecodeError:
            return False, None, (
                f"[{sys_info['name']}]接口返回的不是有效的JSON格式"
            )
        except Exception as e:
            return False, None, (
                f"获取[{sys_info['name']}]权限时发生未知异常: {type(e).__name__}: {str(e)[:100]}"
            )

    def adjust_permission(self, user_identifier: str, system_code: str,
                          permission_code: str, grant: bool) -> Tuple[bool, str]:
        sys_info = self._get_system_info(system_code)
        if not sys_info:
            return False, f"系统[{system_code}]未配置"

        api_url = sys_info.get("api_url", "")
        if not api_url:
            return False, f"系统[{system_code}]API地址未配置"

        action = "grant" if grant else "revoke"
        action_text = "授予" if grant else "撤销"

        try:
            url = f"{api_url.rstrip('/')}/permissions/adjust"
            payload = {
                "user_identifier": user_identifier,
                "system_code": system_code,
                "permission_code": permission_code,
                "action": action,
            }

            logger.info(f"调用真实系统接口{action_text}权限: {system_code} -> {user_identifier}: {permission_code}")

            response = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )

            if response.status_code != 200:
                return False, (
                    f"权限调整接口调用失败: HTTP {response.status_code}, "
                    f"系统[{sys_info['name']}]响应异常"
                )

            result = response.json()
            if not result.get("success", False):
                return False, (
                    f"{action_text}权限失败: 系统[{sys_info['name']}]返回错误: "
                    f"{result.get('message', '未知错误')}"
                )

            return True, f"已成功{action_text}权限: {permission_code}"

        except requests.Timeout:
            return False, f"调整权限超时，[{sys_info['name']}]系统响应超时"
        except requests.ConnectionError:
            return False, f"无法连接到[{sys_info['name']}]系统，权限调整失败"
        except Exception as e:
            return False, f"调整权限时发生异常: {type(e).__name__}: {str(e)[:100]}"


class MockBusinessSystemAdapter(BusinessSystemAdapter):
    def __init__(self):
        self.use_random_permissions = False
        self.should_fail = False
        self.fixed_permissions: Dict[str, Dict[str, bool]] = {}

    def set_fixed_permissions(self, system_code: str, permissions: Dict[str, bool]):
        self.fixed_permissions[system_code] = permissions
        logger.info(f"设置[{system_code}]的固定权限数据，共{len(permissions)}项")

    def set_use_random(self, use: bool):
        self.use_random_permissions = use
        status = "启用" if use else "禁用"
        logger.info(f"Mock适配器随机权限生成已{status}")

    def set_should_fail(self, fail: bool, system_code: Optional[str] = None):
        self.should_fail = fail
        self._fail_system = system_code
        status = "启用" if fail else "禁用"
        target = f"[{system_code}]" if system_code else "全局"
        logger.info(f"Mock适配器{target}接口失败模拟已{status}")

    def fetch_permissions(self, user_identifier: str, system_code: str) -> Tuple[bool, Optional[Dict[str, bool]], str]:
        if self.should_fail and (self._fail_system is None or self._fail_system == system_code):
            from app.utils import get_system_name
            sys_name = get_system_name(system_code)
            return False, None, (
                f"模拟接口失败: [{sys_name}]系统维护中，暂时无法获取权限数据"
            )

        if system_code in self.fixed_permissions:
            perms = self.fixed_permissions[system_code]
            from app.utils import get_system_name
            sys_name = get_system_name(system_code)
            return True, perms, f"从Mock数据获取[{sys_name}]权限，共{len(perms)}项（固定数据）"

        if self.use_random_permissions:
            from app.services.snapshot_service import SnapshotSyncService
            from app.models import User
            user_role = "user"
            perms = SnapshotSyncService._generate_mock_permissions(system_code, user_role)
            from app.utils import get_system_name
            sys_name = get_system_name(system_code)
            return True, perms, f"从Mock数据获取[{sys_name}]权限，共{len(perms)}项（随机生成）"

        from app.utils import get_system_name
        sys_name = get_system_name(system_code)
        return False, None, (
            f"Mock适配器未配置[{sys_name}]的固定权限数据，"
            f"且随机生成模式已禁用。请先调用 set_fixed_permissions() 设置权限数据。"
        )

    def adjust_permission(self, user_identifier: str, system_code: str,
                          permission_code: str, grant: bool) -> Tuple[bool, str]:
        action_text = "授予" if grant else "撤销"

        if system_code not in self.fixed_permissions:
            self.fixed_permissions[system_code] = {}

        self.fixed_permissions[system_code][permission_code] = grant
        logger.info(f"Mock适配器{action_text}权限: {system_code} -> {user_identifier}: {permission_code} = {grant}")
        return True, f"Mock模式已{action_text}权限: {permission_code}"


class AdapterFactory:
    _instance: Optional[BusinessSystemAdapter] = None
    _adapter_type: str = "real"

    @classmethod
    def get_adapter(cls) -> BusinessSystemAdapter:
        if cls._instance is None:
            cls._instance = cls._create_adapter()
        return cls._instance

    @classmethod
    def _create_adapter(cls) -> BusinessSystemAdapter:
        if cls._adapter_type == "mock":
            logger.info("创建 Mock 业务系统适配器（仅用于开发测试）")
            return MockBusinessSystemAdapter()
        else:
            logger.info("创建 真实 业务系统适配器（调用生产接口）")
            return RealBusinessSystemAdapter()

    @classmethod
    def set_adapter_type(cls, adapter_type: str):
        if adapter_type not in ["real", "mock"]:
            raise ValueError(f"不支持的适配器类型: {adapter_type}，可选: real, mock")
        cls._adapter_type = adapter_type
        cls._instance = None
        logger.info(f"业务系统适配器已切换为: {adapter_type}")

    @classmethod
    def get_adapter_type(cls) -> str:
        return cls._adapter_type

    @classmethod
    def get_mock_adapter(cls) -> Optional[MockBusinessSystemAdapter]:
        adapter = cls.get_adapter()
        if isinstance(adapter, MockBusinessSystemAdapter):
            return adapter
        return None


def get_business_system_adapter() -> BusinessSystemAdapter:
    return AdapterFactory.get_adapter()
