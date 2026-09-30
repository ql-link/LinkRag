import { validateRegister } from './validation';

const ok = { username: 'chenmo', email: 'chenmo@example.com', password: 'abc12345', confirm: 'abc12345' };

describe('validateRegister', () => {
  it('accepts a valid form', () => {
    expect(validateRegister(ok)).toEqual({});
  });

  it('rejects bad username, email, weak password and mismatch', () => {
    const e = validateRegister({ username: 'a!', email: 'x', password: 'abcdefgh', confirm: 'abcdefg' });
    expect(Object.keys(e).sort()).toEqual(['confirm', 'email', 'password', 'username']);
    expect(e.confirm).toBe('两次输入的密码不一致');
  });
});
