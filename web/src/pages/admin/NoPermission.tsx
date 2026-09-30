import { Link } from 'react-router-dom';

import { actionBtn, StateFeedback } from './StateFeedback';

/** 设计稿 A2：非 ADMIN 账号访问管理台 */
export function NoPermission() {
  return (
    <div className="flex min-h-full items-center justify-center">
      <StateFeedback
        kind="denied"
        size="page"
        title="当前账户没有管理员权限"
        desc="管理台仅对 ADMIN 角色开放。如需访问，请联系平台管理员为你的账号分配权限。"
        action={
          <Link to="/home" className={actionBtn}>
            返回用户端
          </Link>
        }
      />
    </div>
  );
}
