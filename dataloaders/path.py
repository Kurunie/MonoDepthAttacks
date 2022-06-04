class Path(object):
    @staticmethod
    def db_root_dir(database):
        if database == 'nyu':
            return '~/MonoDepthAttacks/data/nyu_depth_v2'
        elif database == 'kitti':
            return '~/MonoDepthAttacks/data/kitti'
        else:
            print('Database {} not available.'.format(database))
            raise NotImplementedError
