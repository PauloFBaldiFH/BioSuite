import {describe,expect,it} from 'vitest';
import {ingressFor,libraryIdFromTunnelName,libraryIdFromComment} from '../src/provision-steps';
import {publishedHostnames} from '../src/names';

describe('BioSuite Galaxy profile',()=>{
  it('uses only the configured local port and one hostname',()=>{
    expect(ingressFor({opac:'bio-lab.koha.nexus',staff:'bio-lab-admin.koha.nexus'},false,
      {koha:true,tainacan:false,galaxyPort:8087})).toEqual([
        {hostname:'bio-lab.koha.nexus',service:'http://127.0.0.1:8087'},{service:'http_status:404'}]);
    expect(publishedHostnames('lab',{APPLICATION:'galaxy',NAME_PREFIX:'bio-',STAFF_SUFFIX:'-admin',ZONE_NAME:'koha.nexus'},
      {koha:true,tainacan:false})).toEqual({galaxy:'bio-lab.koha.nexus'});
  });
  it('refuses invalid ports and never adopts Nexus resource prefixes',()=>{
    expect(()=>ingressFor({opac:'bio-lab.koha.nexus',staff:'unused'},false,{koha:true,tainacan:false,galaxyPort:22})).toThrow();
    expect(libraryIdFromTunnelName('kei-lib-existing')).toBeNull();
    expect(libraryIdFromComment('kei:lib:existing')).toBeNull();
    expect(libraryIdFromTunnelName('biosuite-instance-own')).toBe('own');
  });
});
